"""
apps/subscriptions/middleware.py

Django middleware that enforces subscription access on all API endpoints.

Rules:
  - /admin/                          → always pass (Django admin handles its own auth)
  - /api/v1/auth/                    → always pass (login, register, token refresh)
  - /api/v1/subscriptions/           → always pass (owners need to read their own status)
  - role == 'admin'                  → always pass (Cameltech platform admins)
  - unauthenticated requests         → pass (IsAuthenticated handles those)
  - role in ('owner', 'staff') with
    an active subscription           → pass
  - role in ('owner', 'staff') with
    a non-active subscription        → HTTP 402 with code 'subscription_required'

HTTP 402 response shape (same envelope as apps.core.response):
  {
    "success": false,
    "message": "...",
    "data": null,
    "errors": {
      "code": "subscription_required",
      "subscription_status": "pending_payment",
      "trial_fee": 10000
    }
  }

Why middleware instead of a DRF permission class:
  A permission class must be added to every view. Adding it to
  DEFAULT_PERMISSION_CLASSES would fire before the view's own AllowAny
  override. Using middleware with JWTAuthentication.authenticate() lets us
  intercept at the transport layer without touching individual views.
"""

import json

from django.http import HttpResponse


# Paths that bypass the subscription check entirely
_EXEMPT_PREFIXES = (
    "/admin/",
    "/api/v1/auth/",          # login, register, token refresh/verify
    "/api/v1/subscriptions/", # owners need to read their subscription status
)


class SubscriptionAccessMiddleware:
    """
    Block API access for owners/staff whose organisation's subscription
    is not currently active (status != trial/active OR end_date in the past).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        # Fast-path: skip non-API and exempt prefixes
        if not path.startswith("/api/v1/") or any(
            path.startswith(p) for p in _EXEMPT_PREFIXES
        ):
            return self.get_response(request)

        # Attempt JWT authentication — DRF's JWTAuthentication reads the
        # Authorization header and returns (user, token) or None.
        user = self._get_jwt_user(request)
        if user is None or not user.is_authenticated:
            return self.get_response(request)

        # Platform admins bypass all subscription checks
        if user.role == "admin":
            return self.get_response(request)

        # For owners and staff: check the organisation's subscription
        org = user.get_organisation
        if org is None:
            # No organisation → let the view decide (may be a newly seeded user)
            return self.get_response(request)

        sub = org.subscriptions.order_by("-created_at").first()
        if sub is None:
            # No subscription record at all → let the view decide
            return self.get_response(request)

        if not sub.is_active_now:
            return self._subscription_required_response(sub)

        return self.get_response(request)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_jwt_user(request):
        """
        Authenticate the request using Simple JWT without triggering DRF's
        full authentication stack. Returns the User or None on any failure.
        """
        try:
            from rest_framework_simplejwt.authentication import JWTAuthentication
            result = JWTAuthentication().authenticate(request)
            if result is None:
                return None
            user, _ = result
            return user
        except Exception:
            return None

    @staticmethod
    def _subscription_required_response(sub) -> HttpResponse:
        body = {
            "success": False,
            "message": (
                "Your subscription is not active. "
                f"Please pay TZS {sub.trial_fee:,} to activate your 7-day trial."
                if sub.is_trial
                else "Your subscription has expired. Please renew to continue."
            ),
            "data": None,
            "errors": {
                "code":                "subscription_required",
                "subscription_status": sub.status,
                "trial_fee":           sub.trial_fee,
                "is_trial":            sub.is_trial,
                "end_date":            str(sub.end_date),
            },
        }
        return HttpResponse(
            json.dumps(body),
            status=402,
            content_type="application/json",
        )
