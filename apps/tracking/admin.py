"""
apps/tracking/admin.py

Django Admin registrations for tracking models +
the custom AdminSite that drives the dashboard.

The custom admin site overrides the default index page to inject
chart data — daily logins, top endpoints, API calls per day, new
registrations — all rendered with Chart.js loaded from CDN.
"""

import json
from collections import defaultdict
from datetime import date, timedelta

from django.contrib import admin
from django.contrib.admin import AdminSite
from django.db.models import Avg, Count, Q
from django.utils import timezone
from django.utils.html import format_html

from .models import LoginEvent, RequestLog


# ── Dashboard stats helpers ───────────────────────────────────────────────────

def _last_n_days(n):
    """Return a list of date strings for the last n days (oldest first)."""
    today = timezone.now().date()
    return [(today - timedelta(days=i)).isoformat() for i in reversed(range(n))]


def _get_dashboard_context():
    """
    Build all chart datasets and KPI numbers for the admin dashboard.
    Called once per admin index page load.
    """
    today  = timezone.now().date()
    _30ago = today - timedelta(days=29)
    _7ago  = today - timedelta(days=6)

    # ── KPI cards ────────────────────────────────────────────────────────────

    from apps.accounts.models import Organisation, User

    total_orgs   = Organisation.objects.count()
    total_owners = User.objects.filter(role="owner").count()
    total_staff  = User.objects.filter(role="staff").count()

    logins_today = LoginEvent.objects.filter(
        timestamp__date=today
    ).count()

    active_users_today = (
        RequestLog.objects
        .filter(timestamp__date=today, user_id__isnull=False)
        .values("user_id")
        .distinct()
        .count()
    )

    requests_today = RequestLog.objects.filter(timestamp__date=today).count()

    new_orgs_this_month = Organisation.objects.filter(
        created_at__year=today.year,
        created_at__month=today.month,
    ).count()

    # ── Daily logins (last 30 days) ───────────────────────────────────────────

    login_rows = (
        LoginEvent.objects
        .filter(timestamp__date__gte=_30ago)
        .extra(select={"day": "date(timestamp)"})
        .values("day")
        .annotate(count=Count("id"))
    )
    login_by_day = {row["day"]: row["count"] for row in login_rows}
    days_30 = _last_n_days(30)
    daily_logins = {
        "labels": [d[5:] for d in days_30],  # MM-DD format
        "data":   [login_by_day.get(d, 0) for d in days_30],
    }

    # ── API calls per day (last 14 days) ─────────────────────────────────────

    api_rows = (
        RequestLog.objects
        .filter(timestamp__date__gte=today - timedelta(days=13))
        .extra(select={"day": "date(timestamp)"})
        .values("day")
        .annotate(count=Count("id"))
    )
    api_by_day = {row["day"]: row["count"] for row in api_rows}
    days_14 = _last_n_days(14)
    daily_api = {
        "labels": [d[5:] for d in days_14],
        "data":   [api_by_day.get(d, 0) for d in days_14],
    }

    # ── Top 10 endpoints last 7 days ──────────────────────────────────────────

    top_eps = (
        RequestLog.objects
        .filter(timestamp__date__gte=_7ago)
        .values("path", "method")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    top_endpoints = {
        "labels": [f"{r['method']} {r['path']}" for r in top_eps],
        "data":   [r["count"] for r in top_eps],
    }

    # ── New organisations per day (last 30 days) ──────────────────────────────

    org_rows = (
        Organisation.objects
        .filter(created_at__date__gte=_30ago)
        .extra(select={"day": "date(created_at)"})
        .values("day")
        .annotate(count=Count("id"))
    )
    org_by_day = {row["day"]: row["count"] for row in org_rows}
    daily_orgs = {
        "labels": [d[5:] for d in days_30],
        "data":   [org_by_day.get(d, 0) for d in days_30],
    }

    # ── Subscription status breakdown ────────────────────────────────────────

    from apps.subscriptions.models import Subscription

    sub_counts = (
        Subscription.objects
        .values("status")
        .annotate(count=Count("id"))
    )
    status_map = {r["status"]: r["count"] for r in sub_counts}
    sub_data = {
        "labels": ["Pending", "Trial", "Active", "Expired", "Cancelled"],
        "data": [
            status_map.get("pending_payment", 0),
            status_map.get("trial", 0),
            status_map.get("active", 0),
            status_map.get("expired", 0),
            status_map.get("cancelled", 0),
        ],
    }

    # ── Average response time by endpoint (last 7 days) ───────────────────────

    slow_eps = (
        RequestLog.objects
        .filter(timestamp__date__gte=_7ago, duration_ms__gt=0)
        .values("path")
        .annotate(avg_ms=Avg("duration_ms"), calls=Count("id"))
        .filter(calls__gte=5)
        .order_by("-avg_ms")[:8]
    )
    response_times = {
        "labels": [r["path"].replace("/api/v1/", "") for r in slow_eps],
        "data":   [round(r["avg_ms"]) for r in slow_eps],
    }

    return {
        # KPI cards
        "kpi_total_orgs":          total_orgs,
        "kpi_total_owners":        total_owners,
        "kpi_total_staff":         total_staff,
        "kpi_logins_today":        logins_today,
        "kpi_active_users_today":  active_users_today,
        "kpi_requests_today":      requests_today,
        "kpi_new_orgs_this_month": new_orgs_this_month,

        # Charts (JSON strings for inline JS)
        "chart_daily_logins":     json.dumps(daily_logins),
        "chart_daily_api":        json.dumps(daily_api),
        "chart_top_endpoints":    json.dumps(top_endpoints),
        "chart_daily_orgs":       json.dumps(daily_orgs),
        "chart_sub_status":       json.dumps(sub_data),
        "chart_response_times":   json.dumps(response_times),
    }


# ── Custom admin site ─────────────────────────────────────────────────────────

class ZiadaAdminSite(AdminSite):
    """
    Custom admin site that overrides the index view to inject
    dashboard chart data into the template context.
    """
    site_header  = "Ziada POS — Admin"
    site_title   = "Ziada Admin"
    index_title  = "Platform Dashboard"

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}
        try:
            extra_context.update(_get_dashboard_context())
        except Exception:
            pass  # Never crash the admin if stats fail
        return super().index(request, extra_context)


# Instantiate our custom site
ziada_admin = ZiadaAdminSite(name="ziada_admin")


# ── RequestLog admin ──────────────────────────────────────────────────────────

@admin.register(RequestLog)
class RequestLogAdmin(admin.ModelAdmin):
    list_display  = [
        "timestamp_display", "method_badge", "path_display",
        "status_badge", "user_phone", "org_name", "duration_badge",
    ]
    list_filter   = ["method", "status_code"]
    search_fields = ["path", "user_phone", "org_name"]
    date_hierarchy = "timestamp"
    ordering       = ["-timestamp"]
    readonly_fields = [
        "path", "method", "status_code", "user_id",
        "user_phone", "org_name", "duration_ms", "timestamp",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def timestamp_display(self, obj):
        return obj.timestamp.strftime("%d %b %H:%M:%S")
    timestamp_display.short_description = "Time"
    timestamp_display.admin_order_field = "timestamp"

    def method_badge(self, obj):
        colors = {
            "GET":    "#3b82f6",
            "POST":   "#10b981",
            "PATCH":  "#f59e0b",
            "DELETE": "#ef4444",
            "PUT":    "#8b5cf6",
        }
        color = colors.get(obj.method, "#6b7280")
        return format_html(
            '<span style="padding:2px 7px;border-radius:3px;background:{}22;'
            'color:{};font-size:11px;font-weight:600">{}</span>',
            color, color, obj.method,
        )
    method_badge.short_description = "Method"

    def path_display(self, obj):
        return format_html(
            '<code style="font-size:12px">{}</code>', obj.path
        )
    path_display.short_description = "Path"
    path_display.admin_order_field = "path"

    def status_badge(self, obj):
        sc = obj.status_code
        if sc < 300:
            color = "#10b981"
        elif sc < 400:
            color = "#f59e0b"
        elif sc < 500:
            color = "#ef4444"
        else:
            color = "#7f1d1d"
        return format_html(
            '<span style="color:{};font-weight:700">{}</span>', color, sc
        )
    status_badge.short_description = "Status"
    status_badge.admin_order_field = "status_code"

    def duration_badge(self, obj):
        ms = obj.duration_ms
        if ms < 100:
            color = "#10b981"
        elif ms < 500:
            color = "#f59e0b"
        else:
            color = "#ef4444"
        return format_html(
            '<span style="color:{}">{} ms</span>', color, ms
        )
    duration_badge.short_description = "Duration"
    duration_badge.admin_order_field = "duration_ms"


# ── LoginEvent admin ──────────────────────────────────────────────────────────

@admin.register(LoginEvent)
class LoginEventAdmin(admin.ModelAdmin):
    list_display  = [
        "timestamp_display", "user_phone", "user_role_badge",
        "org_name",
    ]
    list_filter   = ["user_role"]
    search_fields = ["user_phone", "org_name"]
    date_hierarchy = "timestamp"
    ordering       = ["-timestamp"]
    readonly_fields = [
        "user_id", "user_phone", "user_role", "org_name", "timestamp",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def timestamp_display(self, obj):
        return obj.timestamp.strftime("%d %b %Y %H:%M")
    timestamp_display.short_description = "Login Time"
    timestamp_display.admin_order_field = "timestamp"

    def user_role_badge(self, obj):
        colors = {
            "admin": "#ef4444",
            "owner": "#3b82f6",
            "staff": "#10b981",
        }
        color = colors.get(obj.user_role, "#6b7280")
        return format_html(
            '<span style="padding:2px 8px;border-radius:4px;background:{}22;'
            'color:{};font-size:11px">{}</span>',
            color, color, obj.user_role.title(),
        )
    user_role_badge.short_description = "Role"
