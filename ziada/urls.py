"""
Ziada POS — Root URL configuration.

All API routes are namespaced under /api/v1/ to allow for future versioning.
Django Admin is available at /admin/ out of the box.

URL structure:
  /admin/                      → Django Admin
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
"""

from django.contrib import admin
from django.urls import include, path

# Customise the Django Admin header/title
admin.site.site_header = "Ziada POS Admin"
admin.site.site_title = "Ziada Admin"
admin.site.index_title = "Ziada POS — Administration"

urlpatterns = [
    # ── Django Admin ──────────────────────────────────────────────────────────
    path("admin/", admin.site.urls),

    # ── API v1 ────────────────────────────────────────────────────────────────
    # All API routes live under /api/v1/ for clean versioning
    path("api/v1/", include([
        # JWT auth — login, refresh, verify (no authentication required)
        path("auth/", include("apps.accounts.api.auth_urls")),

        # Accounts — users, stores, staff profiles
        path("accounts/", include("apps.accounts.api.urls")),

        # Inventory — products, categories, suppliers, stock
        path("inventory/", include("apps.inventory.api.urls")),

        # Transactions — sales, POS, refunds
        path("transactions/", include("apps.transactions.api.urls")),

        # Credits — customer debt (madeni) management
        path("credits/", include("apps.credits.api.urls")),

        # Customers — profiles, segments, loyalty
        path("customers/", include("apps.customers.api.urls")),

        # Analytics — aggregations, trends, insights
        path("analytics/", include("apps.analytics.api.urls")),

        # Reports — generation, export history, scheduled reports
        path("reports/", include("apps.reports.api.urls")),

        # AI — chat, insights, OpenRouter
        path("ai/", include("apps.ai.api.urls")),

        # Suppliers — vendor management, deliveries, payments (AP)
        path("suppliers/", include("apps.suppliers.api.urls")),

        # Stores — multi-store management, KPIs, staff rosters
        path("stores/", include("apps.stores.api.urls")),

        # Notebook — internal memos, ideas, and staff notes (per store)
        path("notebook/", include("apps.notebook.api.urls")),

        # Staff — management, shifts, permissions, performance stats
        path("staff/", include("apps.staff.api.urls")),
    ])),
]
