"""
apps/subscriptions/api/views.py

Subscription API views.

Access rules:
  GET  /plans/                             → AllowAny (shown on registration/pricing page)
  POST /plans/                             → SystemAdmin only
  PATCH/DELETE /plans/{id}/               → SystemAdmin only
  GET  /my-subscription/                  → authenticated owner
  GET  /store-limit/                       → authenticated owner (store add gate)
  GET  /all/                              → SystemAdmin only
  POST /all/{id}/activate/                → SystemAdmin only
  PATCH /all/{id}/extra-stores/           → SystemAdmin only

Store limit flow:
  1. Owner clicks "Add Store" in UI
  2. UI calls GET /api/v1/subscriptions/store-limit/
  3. If can_add_store=true  → UI enables the Add Store form
  4. If can_add_store=false → UI shows "At limit. Contact us." message with pricing
  5. Owner pays 12,000 TZS/month outside the system (M-Pesa / bank)
  6. Owner tells Cameltech admin (WhatsApp/phone)
  7. Admin opens Django admin → Subscriptions → finds the org's subscription
     → changes extra_stores from 0 to 1 (or uses PATCH /all/{id}/extra-stores/)
  8. max_stores on Organisation is automatically updated
  9. Owner can now add their new store
"""

import logging

from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.core.permissions import IsOwner, IsSystemAdmin
from apps.core.response import created_response, error_response, success_response

from ..models import Subscription, SubscriptionPlan
from .serializers import (
    ExtraStoreSerializer,
    SubscriptionActivateSerializer,
    SubscriptionPlanSerializer,
    SubscriptionSerializer,
)

logger = logging.getLogger(__name__)

# Extra store price per month (TZS) — used in limit-check responses
# This is also stored on SubscriptionPlan.extra_store_price_per_month.
# We keep a fallback constant here so the store-limit endpoint works even
# before any plans exist (e.g. during the trial period).
_DEFAULT_EXTRA_STORE_PRICE = 12000


def _sync_org_max_stores(subscription):
    """
    Keep organisation.max_stores in sync with the subscription.

    Called whenever extra_stores or the plan changes on a Subscription.
    Using the model property ensures the calculation is always consistent.
    """
    org = subscription.organisation
    new_max = subscription.max_stores_allowed
    if org.max_stores != new_max:
        org.max_stores = new_max
        org.save(update_fields=["max_stores", "updated_at"])
    return org


# ── Subscription Plans (admin-configurable pricing) ───────────────────────────

class SubscriptionPlanViewSet(ModelViewSet):
    """
    GET    /api/v1/subscriptions/plans/       → list active plans (AllowAny)
    GET    /api/v1/subscriptions/plans/{id}/  → plan detail (AllowAny)
    POST   /api/v1/subscriptions/plans/       → create plan (SystemAdmin)
    PATCH  /api/v1/subscriptions/plans/{id}/  → update plan (SystemAdmin)
    DELETE /api/v1/subscriptions/plans/{id}/  → deactivate plan (SystemAdmin)
    """

    queryset         = SubscriptionPlan.objects.all()
    serializer_class = SubscriptionPlanSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return [IsAuthenticated(), IsSystemAdmin()]

    def get_queryset(self):
        qs = super().get_queryset()
        # Public listing → only active plans
        if not (self.request.user.is_authenticated and
                getattr(self.request.user, "role", None) == "admin"):
            qs = qs.filter(is_active=True)
        return qs.order_by("sort_order", "price_per_month")

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        return success_response(
            data=SubscriptionPlanSerializer(qs, many=True).data,
            message=f"{qs.count()} plan(s) available.",
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        plan = serializer.save()
        logger.info("Admin %s created plan '%s'.", request.user.phone, plan.name)
        return created_response(
            data=SubscriptionPlanSerializer(plan).data,
            message=f"Plan '{plan.name}' created.",
        )

    def partial_update(self, request, *args, **kwargs):
        plan = self.get_object()
        serializer = self.get_serializer(plan, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        serializer.save()
        return success_response(
            data=SubscriptionPlanSerializer(plan).data,
            message="Plan updated.",
        )

    def destroy(self, request, *args, **kwargs):
        plan = self.get_object()
        plan.is_active = False
        plan.save(update_fields=["is_active", "updated_at"])
        return success_response(message=f"Plan '{plan.name}' deactivated.")


# ── Store-Limit Check ─────────────────────────────────────────────────────────

class StoreLimitView(APIView):
    """
    GET /api/v1/subscriptions/store-limit/

    Returns whether the authenticated owner can add another store right now.

    The UI uses this to:
      - Enable or disable the "Add Store" button
      - Show the correct message / pricing when the owner is at their limit
      - Display how many slots remain

    Response shape:
    {
      "can_add_store": true | false,
      "current_active_stores": 2,
      "max_stores_allowed": 3,
      "remaining_slots": 1,
      "extra_store_price_per_month": 12000,
      "subscription_status": "trial | active | expired | pending_payment | cancelled",
      "subscription_is_active": true,
      "days_remaining": 5,
      "message": "You can add 1 more store."
                 OR
                 "You have reached your 3-store limit. Additional stores cost
                  12,000 TZS/month. Contact Ziada support to purchase more."
    }
    """

    permission_classes = [IsAuthenticated, IsOwner]

    def get(self, request):
        org = request.user.get_organisation
        if not org:
            return error_response("No organisation linked to this account.", status=400)

        current = org.stores.filter(is_active=True).count()
        max_allowed = org.max_stores
        remaining = max(0, max_allowed - current)
        can_add = remaining > 0

        # Get pricing from the active subscription's plan, or fall back to constant
        sub = org.subscriptions.order_by("-created_at").first()
        extra_price = _DEFAULT_EXTRA_STORE_PRICE
        sub_status = None
        sub_active = False
        days_remaining = 0

        if sub:
            sub_status = sub.status
            sub_active = sub.is_active_now
            days_remaining = sub.days_remaining
            if sub.plan and sub.plan.extra_store_price_per_month:
                extra_price = sub.plan.extra_store_price_per_month

        if can_add:
            message = (
                f"You can add {remaining} more store{'s' if remaining > 1 else ''}."
                if remaining < 10
                else "You can add more stores."
            )
        else:
            message = (
                f"You have reached your {max_allowed}-store limit. "
                f"Additional stores cost {extra_price:,} TZS/month. "
                "Contact Ziada support to purchase more store slots."
            )

        return success_response(
            data={
                "can_add_store":              can_add,
                "current_active_stores":      current,
                "max_stores_allowed":         max_allowed,
                "remaining_slots":            remaining,
                "extra_store_price_per_month": extra_price,
                "subscription_status":        sub_status,
                "subscription_is_active":     sub_active,
                "days_remaining":             days_remaining,
                "message":                    message,
            },
            message=message,
        )


# ── Owner Subscription ────────────────────────────────────────────────────────

class MySubscriptionView(APIView):
    """
    GET /api/v1/subscriptions/my-subscription/
    Returns the current (most recent) subscription for the owner's organisation.
    """

    permission_classes = [IsAuthenticated, IsOwner]

    def get(self, request):
        org = request.user.get_organisation
        if not org:
            return error_response("No organisation linked to this account.", status=400)

        sub = (
            Subscription.objects
            .select_related("plan", "organisation")
            .filter(organisation=org)
            .order_by("-created_at")
            .first()
        )
        if not sub:
            return error_response("No subscription found.", status=404)

        return success_response(
            data=SubscriptionSerializer(sub).data,
            message="Subscription retrieved.",
        )


# ── Admin Subscription Management ─────────────────────────────────────────────

class SubscriptionViewSet(ReadOnlyModelViewSet):
    """
    SystemAdmin-only full subscription list and management.

    GET    /api/v1/subscriptions/all/                   → list all subscriptions
    GET    /api/v1/subscriptions/all/{id}/              → subscription detail
    POST   /api/v1/subscriptions/all/{id}/activate/     → confirm payment + activate
    PATCH  /api/v1/subscriptions/all/{id}/extra-stores/ → grant extra store slots
    """

    queryset = Subscription.objects.select_related(
        "organisation", "plan", "activated_by"
    ).order_by("-created_at")
    serializer_class   = SubscriptionSerializer
    permission_classes = [IsAuthenticated, IsSystemAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        # Optional filters
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        org_id = self.request.query_params.get("organisation")
        if org_id:
            qs = qs.filter(organisation_id=org_id)
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(SubscriptionSerializer(page, many=True).data)
        return success_response(
            data=SubscriptionSerializer(qs, many=True).data,
            message=f"{qs.count()} subscription(s).",
        )

    def retrieve(self, request, *args, **kwargs):
        sub = self.get_object()
        return success_response(data=SubscriptionSerializer(sub).data)

    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        """
        POST /api/v1/subscriptions/all/{id}/activate/

        Cameltech admin confirms payment received and activates the subscription.

        After activation:
          - subscription.status → 'trial' or 'active'
          - organisation.plan   → 'free' (trial) or 'pro' (active)
          - organisation.max_stores is synced to plan.included_stores + extra_stores
        """
        sub = self.get_object()
        serializer = SubscriptionActivateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        data = serializer.validated_data
        sub.status            = data["status"]
        sub.activated_by      = request.user
        sub.payment_reference = data.get("payment_reference", sub.payment_reference)
        sub.payment_date      = data.get("payment_date") or timezone.now().date()
        sub.amount_paid       = data.get("amount_paid", sub.amount_paid)
        sub.notes             = data.get("notes", sub.notes)
        sub.save()

        # Sync organisation plan label and max_stores
        org = sub.organisation
        if data["status"] == Subscription.STATUS_ACTIVE:
            org.plan = "pro"
        else:
            org.plan = "free"
        org.save(update_fields=["plan", "updated_at"])

        # Always keep max_stores in sync after any status change
        _sync_org_max_stores(sub)

        logger.info(
            "Admin %s activated subscription %s for org '%s' (status=%s).",
            request.user.phone, sub.id, sub.organisation.name, data["status"],
        )
        return success_response(
            data=SubscriptionSerializer(sub).data,
            message=f"Subscription activated ({sub.get_status_display()}).",
        )

    @action(detail=True, methods=["patch"], url_path="extra-stores")
    def extra_stores(self, request, pk=None):
        """
        PATCH /api/v1/subscriptions/all/{id}/extra-stores/

        Grant additional store slots to an organisation.

        Payment is handled outside the system — admin calls this after confirming
        the owner has paid 12,000 TZS/month per additional store.

        Effect:
          - subscription.extra_stores is updated
          - organisation.max_stores is recalculated and saved
          - Owner can now create the new store(s)
        """
        sub = self.get_object()
        serializer = ExtraStoreSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        old_extra = sub.extra_stores
        sub.extra_stores = serializer.validated_data["extra_stores"]
        sub.save(update_fields=["extra_stores", "updated_at"])

        # Sync max_stores on organisation
        org = _sync_org_max_stores(sub)

        logger.info(
            "Admin %s updated extra_stores for org '%s': %d → %d (max_stores now %d).",
            request.user.phone, org.name, old_extra, sub.extra_stores, org.max_stores,
        )

        return success_response(
            data={
                **SubscriptionSerializer(sub).data,
                "org_max_stores_now": org.max_stores,
            },
            message=(
                f"Extra store slots updated to {sub.extra_stores}. "
                f"Organisation can now have up to {org.max_stores} stores."
            ),
        )
