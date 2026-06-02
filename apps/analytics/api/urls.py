"""
apps/analytics/api/urls.py

Analytics routes. Mounted at: /api/v1/analytics/

  GET /overview/        → KPIs + trend + payment mix + top products (all-in-one)
  GET /summary/         → KPIs only (lighter, used by dashboard page)
  GET /trend/           → Day-by-day revenue series
  GET /payment-mix/     → Revenue by method (donut chart data)
  GET /top-products/    → Most sold products by revenue

  GET /sales/           → Sales sub-page: category breakdown, DOW avg, hourly pattern
  GET /products/        → Products sub-page: full product table (margin + trend + category)
  GET /customers/       → Customers sub-page: visits, segments, retention cohorts, top customers
  GET /cashflow/        → Cashflow sub-page: inflow/COGS/net, running balance, expenses
  GET /dashboard/       → All dashboard widgets in one call (hourly + KPIs + payment mix + low stock)

All endpoints support:
  ?range=7d|30d|90d|ytd
  ?date_from=YYYY-MM-DD
  ?date_to=YYYY-MM-DD

Additional params:
  /products/?category=Grocery    → filter by category name
  /products/?sort=revenue|units|margin|profit
"""

from django.urls import path

from .views import (
    AnalyticsOverviewView,
    AnalyticsSummaryView,
    CashflowView,
    CustomerAnalyticsView,
    DashboardView,
    PaymentMixView,
    ProductPerformanceView,
    RevenueTrendView,
    SalesAnalyticsView,
    TopProductsView,
)

urlpatterns = [
    # ── Original endpoints ─────────────────────────────────────────────────────
    path("overview/",      AnalyticsOverviewView.as_view(),  name="analytics-overview"),
    path("summary/",       AnalyticsSummaryView.as_view(),   name="analytics-summary"),
    path("trend/",         RevenueTrendView.as_view(),        name="analytics-trend"),
    path("payment-mix/",   PaymentMixView.as_view(),          name="analytics-payment-mix"),
    path("top-products/",  TopProductsView.as_view(),         name="analytics-top-products"),

    # ── Sub-page endpoints ─────────────────────────────────────────────────────
    path("sales/",         SalesAnalyticsView.as_view(),      name="analytics-sales"),
    path("products/",      ProductPerformanceView.as_view(),   name="analytics-products"),
    path("customers/",     CustomerAnalyticsView.as_view(),    name="analytics-customers"),
    path("cashflow/",      CashflowView.as_view(),             name="analytics-cashflow"),

    # ── Dashboard ──────────────────────────────────────────────────────────────
    path("dashboard/",     DashboardView.as_view(),            name="analytics-dashboard"),
]
