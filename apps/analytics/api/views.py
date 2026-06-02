"""
apps/analytics/api/views.py

API views for the Analytics app.

Referenced UI pages:
  /                        → DashboardView (KPIs, hourly chart, payment mix, top products, low stock)
  /analytics               → AnalyticsOverviewView (KPIs + revenue trend + payment mix)
  /analytics/sales         → SalesAnalyticsView (category, DOW, hourly breakdown)
  /analytics/products      → ProductPerformanceView (full product table with margin + trend)
  /analytics/customers     → CustomerAnalyticsView (visits, segments, cohorts, top customers)
  /analytics/cashflow      → CashflowView (inflow/COGS/net, running balance, expense breakdown)

Endpoints:
  GET /api/v1/analytics/overview/         → KPIs + trend + payment mix + top products
  GET /api/v1/analytics/summary/          → KPIs only (dashboard header cards)
  GET /api/v1/analytics/trend/            → Day-by-day revenue series
  GET /api/v1/analytics/payment-mix/      → Revenue by method
  GET /api/v1/analytics/top-products/     → Most sold products by revenue
  GET /api/v1/analytics/sales/            → Category breakdown, DOW avg, hourly pattern
  GET /api/v1/analytics/products/         → Full product performance table
  GET /api/v1/analytics/customers/        → Customer visits, segments, cohorts, top customers
  GET /api/v1/analytics/cashflow/         → Cashflow totals, daily, running balance, expenses
  GET /api/v1/analytics/dashboard/        → All dashboard widgets (single request)

Query params (all date-range endpoints):
  ?range=7d|30d|90d|ytd
  ?date_from=YYYY-MM-DD
  ?date_to=YYYY-MM-DD
"""

import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.response import success_response

from ..services import (
    get_cashflow,
    get_customer_analytics,
    get_dashboard_data,
    get_kpi_summary,
    get_payment_mix,
    get_product_performance,
    get_revenue_trend,
    get_sales_breakdown,
    get_top_products,
    parse_date_range,
)

logger = logging.getLogger(__name__)


# ── Existing views ────────────────────────────────────────────────────────────

class AnalyticsOverviewView(APIView):
    """
    GET /api/v1/analytics/overview/

    Returns all data needed for the /analytics page in a single request:
      - KPI strip (revenue, profit, transactions, customers)
      - Revenue trend (day-by-day series)
      - Payment mix (method breakdown)
      - Top 5 products

    The frontend can request specific sections via ?sections=kpis,trend,mix,products
    but by default returns everything.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return full analytics overview for the authenticated user's store."""
        store = request.user.store
        start, end = parse_date_range(request.query_params)

        # Determine which sections to include (default: all)
        sections = request.query_params.get("sections", "kpis,trend,mix,products")
        include = set(sections.split(","))

        data = {
            "date_from": start.isoformat(),
            "date_to":   end.isoformat(),
            "range":     request.query_params.get("range", "30d"),
        }

        if "kpis" in include:
            data["kpis"] = get_kpi_summary(store, start, end)

        if "trend" in include:
            data["trend"] = get_revenue_trend(store, start, end)

        if "mix" in include:
            data["payment_mix"] = get_payment_mix(store, start, end)

        if "products" in include:
            data["top_products"] = get_top_products(store, start, end, limit=5)

        return success_response(data=data, message="Analytics overview.")


class AnalyticsSummaryView(APIView):
    """
    GET /api/v1/analytics/summary/

    Returns KPI aggregate stats only (same as overview kpis section).
    Used by the dashboard page (/page.tsx) header cards and the
    /analytics overview KPI strip.

    Lighter than the full overview when only KPIs are needed.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return KPI summary for the store."""
        store = request.user.store
        start, end = parse_date_range(request.query_params)
        kpis = get_kpi_summary(store, start, end)
        return success_response(
            data={**kpis, "date_from": start.isoformat(), "date_to": end.isoformat()},
            message="Analytics summary.",
        )


class RevenueTrendView(APIView):
    """
    GET /api/v1/analytics/trend/

    Day-by-day revenue series — used to render the area chart
    on the /analytics page.

    Result: list of { date, label, revenue, profit, transactions }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return revenue trend data."""
        store = request.user.store
        start, end = parse_date_range(request.query_params)
        trend = get_revenue_trend(store, start, end)
        return success_response(
            data={"trend": trend, "date_from": start.isoformat(), "date_to": end.isoformat()},
            message="Revenue trend.",
        )


class PaymentMixView(APIView):
    """
    GET /api/v1/analytics/payment-mix/

    Revenue breakdown by payment method.
    Used by the Donut chart on /analytics page.

    Result: list of { method, amount, pct }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return payment mix breakdown."""
        store = request.user.store
        start, end = parse_date_range(request.query_params)
        mix = get_payment_mix(store, start, end)
        return success_response(data={"payment_mix": mix}, message="Payment mix.")


class TopProductsView(APIView):
    """
    GET /api/v1/analytics/top-products/

    Top N products by revenue in the period.
    Used by the /analytics/products tab and the dashboard top products widget.

    Query params:
      ?limit=10    → how many products to return (default 10, max 50)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return top products."""
        store = request.user.store
        start, end = parse_date_range(request.query_params)

        try:
            limit = min(int(request.query_params.get("limit", 10)), 50)
        except ValueError:
            limit = 10

        products = get_top_products(store, start, end, limit=limit)
        return success_response(
            data={"top_products": products, "date_from": start.isoformat(), "date_to": end.isoformat()},
            message=f"Top {limit} products.",
        )


# ── New sub-page views ────────────────────────────────────────────────────────

class SalesAnalyticsView(APIView):
    """
    GET /api/v1/analytics/sales/

    Detailed sales breakdown for the /analytics/sales sub-page.

    Returns:
      category_breakdown — revenue by product category with trend vs prior period
      day_of_week        — average revenue per weekday (Mon–Sun)
      hourly_pattern     — average revenue per hour slot 07:00–20:00

    Also includes the standard KPI strip and revenue trend so the page
    can populate its top cards without an extra request.

    Query params:
      ?range=7d|30d|90d|ytd  (default: 30d)
      ?date_from, ?date_to
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        store = request.user.store
        start, end = parse_date_range(request.query_params)

        breakdown = get_sales_breakdown(store, start, end)
        kpis      = get_kpi_summary(store, start, end)
        trend     = get_revenue_trend(store, start, end)

        return success_response(
            data={
                "date_from": start.isoformat(),
                "date_to":   end.isoformat(),
                "kpis":      kpis,
                "trend":     trend,
                **breakdown,    # category_breakdown, day_of_week, hourly_pattern
            },
            message="Sales analytics.",
        )


class ProductPerformanceView(APIView):
    """
    GET /api/v1/analytics/products/

    Full product performance table for the /analytics/products sub-page.

    Returns every product sold in the period with:
      product_id, product_name, product_sku, category,
      units_sold, revenue, cost, profit, margin_pct,
      trend_pct (vs prior period), revenue_share_pct.

    Query params:
      ?range=7d|30d|90d|ytd      (default: 30d)
      ?date_from, ?date_to
      ?category=Grocery           (optional: filter to one category)
      ?sort=revenue|units|margin  (default: revenue)

    Differences from top-products/:
      - Returns ALL products (not just top N)
      - Includes margin_pct, cost, trend_pct, revenue_share_pct, category
      - Supports category filter
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        store    = request.user.store
        start, end = parse_date_range(request.query_params)
        category = request.query_params.get("category")  # optional filter
        sort_by  = request.query_params.get("sort", "revenue")

        products = get_product_performance(store, start, end, category=category)

        # Optional server-side sort (client can also sort)
        sort_map = {
            "revenue": lambda p: -(p["revenue"]),
            "units":   lambda p: -(p["units_sold"]),
            "margin":  lambda p: -(p["margin_pct"]),
            "profit":  lambda p: -(p["profit"]),
        }
        if sort_by in sort_map:
            products = sorted(products, key=sort_map[sort_by])

        # Aggregate totals for the KPI strip
        total_rev    = sum(p["revenue"]   for p in products)
        total_profit = sum(p["profit"]    for p in products)
        total_units  = sum(p["units_sold"] for p in products)

        return success_response(
            data={
                "date_from": start.isoformat(),
                "date_to":   end.isoformat(),
                "totals": {
                    "revenue":    total_rev,
                    "profit":     total_profit,
                    "margin_pct": round(total_profit / total_rev * 100, 1) if total_rev else 0.0,
                    "units_sold": total_units,
                    "sku_count":  len(products),
                },
                "products": products,
            },
            message=f"Product performance ({len(products)} SKUs).",
        )


class CustomerAnalyticsView(APIView):
    """
    GET /api/v1/analytics/customers/

    Customer analytics for the /analytics/customers sub-page.

    Returns:
      daily_visits      — day-by-day visits split into new vs returning customers
      segments          — customer count and spend per segment
      retention_cohorts — last-4-month cohort table (new, M+1, M+2, M+3)
      top_customers     — top 20 customers by spend in the period

    Query params:
      ?range=7d|30d|90d|ytd  (default: 30d)
      ?date_from, ?date_to
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        store = request.user.store
        start, end = parse_date_range(request.query_params)

        data = get_customer_analytics(store, start, end)

        # Add aggregate KPIs for the page header strip
        total_visits     = sum(d["total"]         for d in data["daily_visits"])
        new_customers    = sum(d["new_customers"]  for d in data["daily_visits"])
        returning        = sum(d["returning"]      for d in data["daily_visits"])
        total_spend      = sum(s["spend"]          for s in data["segments"])
        days             = max((end - start).days + 1, 1)

        return success_response(
            data={
                "date_from": start.isoformat(),
                "date_to":   end.isoformat(),
                "kpis": {
                    "total_visits":       total_visits,
                    "new_customers":      new_customers,
                    "returning":          returning,
                    "retention_rate_pct": round(returning / total_visits * 100, 1) if total_visits else 0.0,
                    "avg_daily_visits":   round(total_visits / days, 1),
                    "total_spend":        total_spend,
                    "avg_visit_value":    total_spend // total_visits if total_visits else 0,
                },
                **data,     # daily_visits, segments, retention_cohorts, top_customers
            },
            message="Customer analytics.",
        )


class CashflowView(APIView):
    """
    GET /api/v1/analytics/cashflow/

    Cashflow analysis for the /analytics/cashflow sub-page.

    Returns:
      totals           — {inflow, cogs, opex, net, net_margin_pct}
      daily            — day-by-day {inflow, cogs, opex, net}
      running_balance  — cumulative net from period start
      expense_breakdown — expense categories with amounts (COGS fully tracked;
                          OPEX items return 0 — expense tracking coming soon)
      payment_inflow   — revenue by payment method (same as /payment-mix/)
      credit_outstanding — {total, customer_count, overdue_count}

    Query params:
      ?range=7d|30d|90d|ytd  (default: 30d)
      ?date_from, ?date_to
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        store = request.user.store
        start, end = parse_date_range(request.query_params)

        data = get_cashflow(store, start, end)
        return success_response(
            data={
                "date_from": start.isoformat(),
                "date_to":   end.isoformat(),
                **data,
            },
            message="Cashflow analytics.",
        )


class DashboardView(APIView):
    """
    GET /api/v1/analytics/dashboard/

    Single endpoint for the main dashboard page (/).

    Returns all dashboard widgets in one call:
      kpis_today   — today's revenue, profit, tickets
      hourly_today — revenue by hour for today's sales chart
      payment_mix  — today's payment method breakdown
      top_products — top 6 products for the last 7 days
      low_stock    — products at or below their min_stock threshold
      credit_kpi   — outstanding credit total + overdue count

    Note: recent_transactions is served via GET /api/v1/transactions/?page=1
    (the transactions list endpoint, sorted by -created_at).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        store = request.user.store
        data  = get_dashboard_data(store)
        return success_response(data=data, message="Dashboard data.")
