"""
apps/reports/apps.py

AppConfig for the reports app.

The reports app provides on-demand and scheduled report generation for
Ziada POS. It aggregates data from transactions, inventory, credits and
customers to produce business reports in CSV or structured-JSON (PDF-ready)
format.

Four report types:
  Sales Summary        — KPIs, daily revenue trend, top products, payment mix
  Inventory Valuation  — stock-on-hand cost/retail value by category
  Tax Statement        — VAT collected and TRA-ready breakdown
  Credit Aged Debtors  — accounts-receivable with aging buckets

Exports are tracked in ReportExport (for history). Recurring reports are
configured in ScheduledReport and sent to email recipients on a
daily/weekly/monthly schedule.
"""

from django.apps import AppConfig


class ReportsConfig(AppConfig):
    """Configuration for the reports Django app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reports"
    verbose_name = "Reports"
