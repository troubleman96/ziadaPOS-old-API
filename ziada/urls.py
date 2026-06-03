"""
Ziada POS — Root URL configuration.

All API routes are namespaced under /api/v1/ to allow for future versioning.
Django Admin is available at /admin/ with a custom dashboard that shows:
  - KPI cards (total orgs, owners, staff, logins today, API requests)
  - Chart.js graphs: daily logins, API calls, top endpoints, new registrations,
    subscription status breakdown, average response times

URL structure:
  /admin/                      → Django Admin (custom dashboard)
  /api/v1/auth/                → JWT token endpoints (login, refresh, verify)
  /api/v1/accounts/            → Users, stores, staff
  /api/v1/inventory/           → Products, categories, suppliers
  /api/v1/transactions/        → Sales transactions, POS
  /api/v1/credits/             → Customer credit (madeni) management
  /api/v1/customers/           → Customer profiles
  /api/v1/analytics/           → Aggregated analytics & charts
  /api/v1/reports/             → Report generation, export history, scheduled reports
  /api/v1/ai/                  → AI chat & insights (OpenRouter)
  /api/v1/suppliers/           → Supplier management, deliveries, payments
  /api/v1/stores/              → Store management, KPIs, staff rosters
  /api/v1/notebook/            → Internal notebook — notes, tags, store-scoped
  /api/v1/staff/               → Staff management — profiles, shifts, permissions, stats
  /api/v1/subscriptions/       → Subscription plans (public), owner status, admin panel
"""

from django.contrib import admin
from django.urls import include, path

# Apply our custom admin site header and custom index with charts.
# The dashboard template (templates/admin/index.html) is found automatically
# because BASE_DIR/templates is in settings.TEMPLATES[0]["DIRS"].
admin.site.site_header  = "Ziada POS — Admin"
admin.site.site_title   = "Ziada Admin"
admin.site.index_title  = "Platform Dashboard"

# Monkey-patch the admin index to inject dashboard chart data.
# This is done here (not in apps/tracking) to avoid circular imports —
# tracking/admin.py imports from accounts models which may not be ready yet.
_original_index = admin.site.__class__.index

def _patched_index(self, request, extra_context=None):
    extra_context = extra_context or {}
    try:
        from apps.tracking.admin import _get_dashboard_context
        from django.utils import timezone as tz
        extra_context.update(_get_dashboard_context())
        extra_context["today"] = tz.now().strftime("%d %b %Y")
    except Exception:
        extra_context.setdefault("today", "")
    return _original_index(self, request, extra_context)

admin.site.__class__.index = _patched_index

urlpatterns = [
    # ── Django Admin (custom dashboard with Chart.js) ─────────────────────────
    path("admin/", admin.site.urls),

    # ── API v1 ────────────────────────────────────────────────────────────────
    path("api/v1/", include([
        path("auth/",          include("apps.accounts.api.auth_urls")),
        path("accounts/",      include("apps.accounts.api.urls")),
        path("inventory/",     include("apps.inventory.api.urls")),
        path("transactions/",  include("apps.transactions.api.urls")),
        path("credits/",       include("apps.credits.api.urls")),
        path("customers/",     include("apps.customers.api.urls")),
        path("analytics/",     include("apps.analytics.api.urls")),
        path("reports/",       include("apps.reports.api.urls")),
        path("ai/",            include("apps.ai.api.urls")),
        path("suppliers/",     include("apps.suppliers.api.urls")),
        path("stores/",        include("apps.stores.api.urls")),
        path("notebook/",      include("apps.notebook.api.urls")),
        path("staff/",         include("apps.staff.api.urls")),
        path("subscriptions/", include("apps.subscriptions.api.urls")),
    ])),
]
