"""
apps/analytics/apps.py

AppConfig for the analytics app.

Provides aggregated performance data for:
  /analytics          → Overview: revenue trend, KPIs, payment mix, AI insights
  /analytics/sales    → Sales breakdown by day/week/method
  /analytics/products → Top-selling and underperforming products
  /analytics/customers → Customer activity and segment breakdown
  /analytics/cashflow → Inflow/outflow reconciliation

The analytics app is read-only — it reads from transactions, credits,
customers, and inventory to build aggregated views. It never writes business data.
"""

from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    """Configuration for the analytics Django app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.analytics"
    verbose_name = "Analytics"

    def ready(self):
        """
        Wire up signals after all apps have loaded.
        Called by Django once the app registry is ready.

        Connects Transaction.post_save → rebuild_daily_summary()
        so that DailySummary rows stay up-to-date automatically.
        """
        from apps.analytics.signals import connect_signals
        connect_signals()
