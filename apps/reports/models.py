"""
apps/reports/models.py

Data models for the reports app.

Two models:
  ScheduledReport  — recurring report configuration (who gets what, how often)
  ReportExport     — audit trail of every report that was generated or downloaded

Design notes:
  - Report file content is NOT stored in the database (it's regenerated on demand
    from the stored date_from / date_to parameters). This avoids large BLOBs in the
    DB and ensures reports always reflect the latest data corrections.
  - ScheduledReport stores recipients as a JSONField (list of email strings).
    This keeps the schema simple for MVP; a full email-queue integration can be
    added later without schema changes.
  - Both models are store-scoped. A user can only see reports for their own store.
"""

from django.conf import settings
from django.db import models

from apps.accounts.models import Organisation, Store
from apps.core.models import BaseModel


# ── Report type + format constants (shared between both models) ───────────────

REPORT_SALES     = "sales"
REPORT_INVENTORY = "inventory"
REPORT_TAX       = "tax"
REPORT_CREDIT    = "credit"

REPORT_TYPE_CHOICES = [
    (REPORT_SALES,     "Sales Summary"),
    (REPORT_INVENTORY, "Inventory Valuation"),
    (REPORT_TAX,       "Tax Statement"),
    (REPORT_CREDIT,    "Credit Aged Debtors"),
]

FORMAT_CSV  = "csv"
FORMAT_JSON = "json"   # Structured JSON — frontend renders as PDF

FORMAT_CHOICES = [
    (FORMAT_CSV,  "CSV"),
    (FORMAT_JSON, "JSON / PDF"),
]

FREQ_DAILY   = "daily"
FREQ_WEEKLY  = "weekly"
FREQ_MONTHLY = "monthly"

FREQUENCY_CHOICES = [
    (FREQ_DAILY,   "Daily"),
    (FREQ_WEEKLY,  "Weekly"),
    (FREQ_MONTHLY, "Monthly"),
]

RANGE_7D    = "7d"
RANGE_30D   = "30d"
RANGE_90D   = "90d"
RANGE_MONTH = "month"   # The current calendar month
RANGE_YTD   = "ytd"

RANGE_CHOICES = [
    (RANGE_7D,    "Last 7 days"),
    (RANGE_30D,   "Last 30 days"),
    (RANGE_90D,   "Last 90 days"),
    (RANGE_MONTH, "This calendar month"),
    (RANGE_YTD,   "Year to date"),
]


# ── ScheduledReport ───────────────────────────────────────────────────────────

class ScheduledReport(BaseModel):
    """
    A recurring report configuration.

    Stores what to generate, how often, and who to email it to.
    The actual generation and email dispatch happens via a management command
    (or Celery task in production): `python manage.py send_scheduled_reports`.

    From the /reports UI → Scheduled tab:
      - Table of schedules with frequency badge, recipient list, toggle, last/next send dates
      - "+ Schedule report" button creates a new row
      - Toggle switch calls PATCH /reports/scheduled/{id}/ {is_enabled: true/false}
    """

    # ── Store context ──────────────────────────────────────────────────────────
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="scheduled_reports",
        help_text="Store this scheduled report belongs to.",
    )
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="scheduled_reports",
        help_text="Organisation (for multi-store scoping).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_scheduled_reports",
        help_text="User who set up this scheduled report.",
    )

    # ── Report spec ────────────────────────────────────────────────────────────
    report_type = models.CharField(
        max_length=20,
        choices=REPORT_TYPE_CHOICES,
        help_text="Which report to generate: sales, inventory, tax, or credit.",
    )

    name = models.CharField(
        max_length=200,
        help_text="Human-readable name shown in the UI, e.g. 'Daily Sales Summary'.",
    )

    frequency = models.CharField(
        max_length=10,
        choices=FREQUENCY_CHOICES,
        default=FREQ_DAILY,
        help_text="How often to run: daily, weekly, or monthly.",
    )

    date_range_preset = models.CharField(
        max_length=10,
        choices=RANGE_CHOICES,
        default=RANGE_30D,
        help_text=(
            "Date range to include in the report. "
            "'month' means the completed calendar month; "
            "'7d' means the 7 days preceding the send date."
        ),
    )

    # ── Recipients ─────────────────────────────────────────────────────────────
    # Stored as a JSON list so the schema stays flat.
    # e.g. ["hamisi@dukakuu.co.tz", "accountant@firm.co.tz"]
    recipients = models.JSONField(
        default=list,
        help_text="List of email addresses to send the report to.",
    )

    # ── State ─────────────────────────────────────────────────────────────────
    is_enabled = models.BooleanField(
        default=True,
        help_text=(
            "When False, this schedule is paused and will not be auto-sent. "
            "Toggled via the switch in the UI."
        ),
    )

    last_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the most recent successful delivery.",
    )

    next_send_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "When the next send will happen. "
            "Calculated by the management command after each dispatch."
        ),
    )

    def __str__(self):
        return f"{self.name} ({self.get_frequency_display()}) → {self.store.name}"

    @property
    def recipient_count(self):
        """Number of email addresses this report is sent to."""
        return len(self.recipients or [])

    class Meta:
        verbose_name = "Scheduled Report"
        verbose_name_plural = "Scheduled Reports"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "is_enabled"]),
        ]


# ── ReportExport ──────────────────────────────────────────────────────────────

class ReportExport(BaseModel):
    """
    Audit record for every report that was generated (manual or scheduled).

    When a user clicks "CSV" or "PDF" on the /reports page, a ReportExport row
    is created to log the event. The file itself is regenerated on download —
    it is NOT stored here — keeping the database lean.

    The history table on /reports → History tab reads these rows.

    From the UI:
      - Shows: report name, period label, format badge, generated date, file size
      - "Download" button calls GET /reports/exports/{id}/download/
    """

    # ── Store context ──────────────────────────────────────────────────────────
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="report_exports",
        help_text="Store the report was generated for.",
    )
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="report_exports",
        help_text="Organisation (for multi-store scoping).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="report_exports",
        help_text="User who generated the export (null for auto-scheduled exports).",
    )

    # ── Report spec ────────────────────────────────────────────────────────────
    report_type = models.CharField(
        max_length=20,
        choices=REPORT_TYPE_CHOICES,
        help_text="Which report type was generated.",
    )

    name = models.CharField(
        max_length=200,
        help_text="Display name shown in history, e.g. 'Sales Summary'.",
    )

    # The human-readable date label shown in the history table
    # e.g. "1 – 24 May 2026", "April 2026"
    period_label = models.CharField(
        max_length=100,
        help_text="Human-readable period label, e.g. '1 – 24 May 2026'.",
    )

    # Exact date bounds used to generate the report (needed for re-download)
    date_from = models.DateField(
        help_text="Start date of the report period (inclusive).",
    )
    date_to = models.DateField(
        help_text="End date of the report period (inclusive).",
    )

    format = models.CharField(
        max_length=10,
        choices=FORMAT_CHOICES,
        default=FORMAT_CSV,
        help_text="Export format: csv or json.",
    )

    # Approximate file size in bytes (calculated when first generated)
    file_size_bytes = models.PositiveIntegerField(
        default=0,
        help_text="Approximate file size in bytes (for display in history table).",
    )

    # FK back to a scheduled report, if this export was auto-generated
    scheduled_report = models.ForeignKey(
        ScheduledReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exports",
        help_text="The scheduled report that triggered this export (null for manual exports).",
    )

    def __str__(self):
        return f"{self.name} | {self.period_label} | {self.format.upper()} | {self.store.name}"

    @property
    def file_size_display(self):
        """Human-readable file size: '284 KB', '1.2 MB', etc."""
        b = self.file_size_bytes
        if b < 1024:
            return f"{b} B"
        if b < 1_048_576:
            return f"{b // 1024} KB"
        return f"{b / 1_048_576:.1f} MB"

    @property
    def is_manual(self):
        """True if this was a manual (on-demand) export, not a scheduled one."""
        return self.scheduled_report_id is None

    class Meta:
        verbose_name = "Report Export"
        verbose_name_plural = "Report Exports"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "report_type"]),
            models.Index(fields=["store", "created_at"]),
        ]
