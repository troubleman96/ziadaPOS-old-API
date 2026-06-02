"""
apps/reports/api/serializers.py

Serializers for the reports app API.

  GenerateReportSerializer     — validates POST /reports/generate/ input
  ScheduledReportSerializer    — full read/write for ScheduledReport
  ScheduledReportListSerializer — lightweight list view
  ReportExportSerializer       — read-only export history row
"""

from django.utils import timezone
from rest_framework import serializers

from ..models import (
    FORMAT_CHOICES,
    FREQUENCY_CHOICES,
    RANGE_CHOICES,
    REPORT_TYPE_CHOICES,
    ReportExport,
    ScheduledReport,
)


# ── GenerateReportSerializer ──────────────────────────────────────────────────

class GenerateReportSerializer(serializers.Serializer):
    """
    Validates the body of POST /api/v1/reports/generate/.

    Either `range` OR both `date_from` + `date_to` must be provided.
    Default range is 30d if nothing is supplied.
    """

    report_type = serializers.ChoiceField(
        choices=REPORT_TYPE_CHOICES,
        help_text="Which report to generate: sales | inventory | tax | credit",
    )
    format = serializers.ChoiceField(
        choices=FORMAT_CHOICES,
        default="csv",
        help_text="Output format: csv (file download) or json (structured data for PDF).",
    )
    range = serializers.ChoiceField(
        choices=["7d", "30d", "90d", "month", "ytd"],
        required=False,
        default="30d",
        help_text="Preset date range shorthand.",
    )
    date_from = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Explicit start date (YYYY-MM-DD). Overrides range if both provided.",
    )
    date_to = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Explicit end date (YYYY-MM-DD). Overrides range if both provided.",
    )

    def validate(self, attrs):
        """If explicit dates provided, validate they are in the right order."""
        date_from = attrs.get("date_from")
        date_to   = attrs.get("date_to")

        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError(
                {"date_to": "date_to must be on or after date_from."}
            )
        return attrs


# ── ScheduledReportSerializer ─────────────────────────────────────────────────

class ScheduledReportSerializer(serializers.ModelSerializer):
    """
    Full serializer for ScheduledReport — used for create, retrieve, and update.

    `recipients` is a JSONField (list of strings). Validation ensures that:
      - It is a list
      - Every element looks like an email address
    """

    recipient_count = serializers.IntegerField(read_only=True)

    class Meta:
        model  = ScheduledReport
        fields = [
            "id",
            "report_type",
            "name",
            "frequency",
            "date_range_preset",
            "recipients",
            "is_enabled",
            "last_sent_at",
            "next_send_at",
            "recipient_count",
            "created_at",
        ]
        read_only_fields = [
            "id", "last_sent_at", "next_send_at",
            "recipient_count", "created_at",
        ]

    def validate_recipients(self, value):
        """Must be a non-empty list of valid-ish email strings."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list of email addresses.")
        if not value:
            raise serializers.ValidationError("At least one recipient is required.")
        for email in value:
            if not isinstance(email, str) or "@" not in email:
                raise serializers.ValidationError(
                    f"Invalid email address: {email!r}"
                )
        return value

    def validate_name(self, value):
        """Strip whitespace and ensure non-empty."""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value


class ScheduledReportListSerializer(serializers.ModelSerializer):
    """
    Compact serializer for the scheduled reports list table.

    Used by GET /api/v1/reports/scheduled/ to return the table rows
    matching the UI's ScheduledTab component.
    """

    class Meta:
        model  = ScheduledReport
        fields = [
            "id",
            "name",
            "report_type",
            "frequency",
            "recipients",
            "is_enabled",
            "last_sent_at",
            "next_send_at",
        ]


# ── ReportExportSerializer ────────────────────────────────────────────────────

class ReportExportSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for the export history table.

    Used by GET /api/v1/reports/exports/ to populate the History tab.
    Includes file_size_display (human-readable) alongside the raw bytes.
    """

    file_size_display = serializers.CharField(read_only=True)
    created_by_name   = serializers.SerializerMethodField()

    class Meta:
        model  = ReportExport
        fields = [
            "id",
            "report_type",
            "name",
            "period_label",
            "format",
            "date_from",
            "date_to",
            "file_size_bytes",
            "file_size_display",
            "created_by_name",
            "created_at",
        ]

    def get_created_by_name(self, obj):
        """Username or 'System' for scheduled auto-exports."""
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return "System"
