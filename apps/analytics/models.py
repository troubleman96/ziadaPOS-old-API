"""
apps/analytics/models.py

DailySummary — pre-aggregated daily stats for fast analytics queries.

Why pre-aggregate?
  The /analytics page loads KPIs and chart data on every visit. Scanning
  all transactions every time would get slow as the dataset grows.
  Instead, a nightly job (or post-save signal on Transaction) updates
  DailySummary for that day, so the analytics endpoint just reads 30-90
  rows instead of scanning thousands of transactions.

When is DailySummary updated?
  1. Signal on Transaction.save(): update_daily_summary_for_today()
  2. Management command: python manage.py rebuild_daily_summaries
     (useful to backfill historical data or fix gaps)

Each row = one day × one store.
"""

from django.db import models

from apps.accounts.models import Store
from apps.core.models import BaseModel


class DailySummary(BaseModel):
    """
    Pre-aggregated daily sales summary for one store and one calendar day.

    Powers the /analytics charts and KPIs without scanning all transactions
    on every page load.

    Table: analytics_dailysummary
    """

    # ── Dimensions ────────────────────────────────────────────────────────────

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="daily_summaries",
        help_text="The store this summary belongs to.",
    )

    # The calendar day this row summarises
    date = models.DateField(
        help_text="Calendar date (YYYY-MM-DD) for this summary.",
    )

    # ── Transaction counts ────────────────────────────────────────────────────

    # Total number of completed transactions (paid + credit, not refunded/void)
    transaction_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of transactions completed on this day.",
    )

    # How many distinct customers transacted (registered customers only)
    customer_count = models.PositiveIntegerField(
        default=0,
        help_text="Distinct registered customers who transacted on this day.",
    )

    # ── Revenue ───────────────────────────────────────────────────────────────

    # Sum of Transaction.total for paid transactions (TZS integer)
    revenue = models.PositiveIntegerField(
        default=0,
        help_text="Total revenue (paid transactions) for this day (TZS).",
    )

    # Sum of Transaction.total for credit transactions (TZS integer)
    credit_revenue = models.PositiveIntegerField(
        default=0,
        help_text="Revenue from credit sales for this day (TZS).",
    )

    # ── Cost & profit ─────────────────────────────────────────────────────────

    cost_total = models.PositiveIntegerField(
        default=0,
        help_text="Total cost of goods sold on this day (TZS).",
    )

    profit = models.IntegerField(
        default=0,
        help_text="Gross profit (total - cost - tax) for this day (TZS).",
    )

    tax_collected = models.PositiveIntegerField(
        default=0,
        help_text="Total VAT collected on this day (TZS).",
    )

    # Refund amount (reduces effective revenue)
    refund_total = models.PositiveIntegerField(
        default=0,
        help_text="Total refunded on this day (TZS).",
    )

    # ── Payment method breakdown ──────────────────────────────────────────────
    # Storing these as integer amounts (not %) for flexibility.
    # Percentages can be computed: (method_x / revenue) * 100

    cash_revenue    = models.PositiveIntegerField(default=0, help_text="Revenue from Cash payments (TZS).")
    mpesa_revenue   = models.PositiveIntegerField(default=0, help_text="Revenue from M-Pesa payments (TZS).")
    tigo_revenue    = models.PositiveIntegerField(default=0, help_text="Revenue from Tigo Pesa payments (TZS).")
    bank_revenue    = models.PositiveIntegerField(default=0, help_text="Revenue from Bank payments (TZS).")
    credit_issued   = models.PositiveIntegerField(default=0, help_text="Amount issued on credit this day (TZS).")

    class Meta:
        """Meta options for DailySummary."""
        db_table = "analytics_dailysummary"
        ordering = ["-date"]
        verbose_name = "Daily Summary"
        verbose_name_plural = "Daily Summaries"

        # One summary per store per day
        unique_together = [("store", "date")]
        indexes = [
            models.Index(fields=["store", "date"], name="idx_daily_store_date"),
        ]

    def __str__(self):
        return f"Summary {self.date} — {self.store.name} | Rev TZS {self.revenue:,}"

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def margin_pct(self) -> float:
        """Gross profit margin percentage for this day."""
        effective_revenue = self.revenue + self.credit_revenue
        if effective_revenue == 0:
            return 0.0
        return round(self.profit / effective_revenue * 100, 1)

    @property
    def avg_ticket(self) -> int:
        """Average transaction value for this day."""
        if self.transaction_count == 0:
            return 0
        return (self.revenue + self.credit_revenue) // self.transaction_count
