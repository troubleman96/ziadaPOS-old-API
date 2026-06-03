"""
apps/tracking/middleware.py

RequestLogMiddleware — logs each API request to the RequestLog table.

Excluded paths (to keep the log clean):
  - /admin/   → admin itself uses the logs; don't log admin browsing
  - /static/  → not API traffic
  - /favicon  → browser noise

The middleware reads request.user AFTER the view returns, so DRF's JWT
authentication has already run and request.user is populated.
"""

import time


# Paths to never log
_SKIP_PREFIXES = ("/admin/", "/static/", "/favicon")


class RequestLogMiddleware:
    """
    WSGI middleware that logs every API request to RequestLog.

    Runs after the view (process_response) so response status and
    authenticated user are both available.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        path = request.path
        if not any(path.startswith(p) for p in _SKIP_PREFIXES):
            self._log(request, response, duration_ms)

        return response

    def _log(self, request, response, duration_ms):
        """Write a RequestLog row. Errors here must never crash the request."""
        try:
            from apps.tracking.models import RequestLog

            user     = request.user
            user_id  = None
            phone    = ""
            org_name = ""

            if user and user.is_authenticated:
                user_id = user.pk
                phone   = getattr(user, "phone", "") or ""
                org     = getattr(user, "get_organisation", None)
                if callable(org):
                    org = org()
                elif org is None:
                    org = getattr(user, "get_organisation", None)
                if org:
                    org_name = str(org.name)

            RequestLog.objects.create(
                path        = request.path[:300],
                method      = request.method,
                status_code = response.status_code,
                user_id     = user_id,
                user_phone  = phone[:15],
                org_name    = org_name[:200],
                duration_ms = duration_ms,
            )
        except Exception:
            pass  # Never let tracking errors surface to the user
