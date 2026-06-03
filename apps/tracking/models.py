"""
apps/tracking/models.py

Lightweight API usage tracking for the Ziada admin dashboard.

Two models:
  RequestLog  — one row per API request (path, method, status, user, timing)
  LoginEvent  — one row per successful login (user, org, timestamp)

Queried by the custom admin dashboard to build:
  - Daily login line chart
  - Top endpoints bar chart
  - API calls per day line chart
  - Active users count

Design notes:
  - Models intentionally do NOT extend BaseModel (UUID PK) because we need
    fast integer PK auto-increment for high-volume insert performance.
  - No FK constraints on user/org so logging never fails due to deleted users.
  - Admin URLs (/admin/*) are excluded from RequestLog to avoid noise.
"""

from django.db import models


class RequestLog(models.Model):
    """
    One record per API request processed by the backend.

    Written by apps.tracking.middleware.RequestLogMiddleware after each
    response. Admin URLs and static file requests are excluded.
    """

    # URL path, normalised (query strings stripped)
    path = models.CharField(
        max_length=300,
        db_index=True,
        help_text="Request path, e.g. '/api/v1/transactions/complete-sale/'",
    )
    method = models.CharField(
        max_length=10,
        help_text="HTTP method: GET, POST, PATCH, DELETE, etc.",
    )
    status_code = models.PositiveSmallIntegerField(
        help_text="HTTP response status code.",
    )

    # Nullable so unauthenticated requests are still logged
    user_id = models.IntegerField(
        null=True, blank=True,
        help_text="PK of the authenticated user (null if unauthenticated).",
    )
    user_phone = models.CharField(
        max_length=15, blank=True,
        help_text="Phone of the authenticated user (cached for display).",
    )
    org_name = models.CharField(
        max_length=200, blank=True,
        help_text="Organisation name (cached for display).",
    )

    duration_ms = models.PositiveIntegerField(
        default=0,
        help_text="Request processing time in milliseconds.",
    )

    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        verbose_name       = "Request Log"
        verbose_name_plural = "Request Logs"
        ordering           = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp", "path"]),
            models.Index(fields=["user_id", "timestamp"]),
        ]

    def __str__(self):
        return f"{self.method} {self.path} → {self.status_code}"


class LoginEvent(models.Model):
    """
    One record per successful login through POST /api/v1/auth/login/.
    Used to power the 'Daily Logins' chart on the admin dashboard.
    """

    user_id   = models.IntegerField(help_text="PK of the logged-in user.")
    user_phone = models.CharField(max_length=15, blank=True)
    user_role  = models.CharField(max_length=20, blank=True)
    org_name   = models.CharField(max_length=200, blank=True)

    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        verbose_name        = "Login Event"
        verbose_name_plural = "Login Events"
        ordering            = ["-timestamp"]
        indexes             = [
            models.Index(fields=["timestamp"]),
            models.Index(fields=["user_id", "timestamp"]),
        ]

    def __str__(self):
        return f"Login: {self.user_phone} @ {self.timestamp:%Y-%m-%d %H:%M}"
