"""
apps/reports/admin.py

Django Admin registrations for the reports app.

Provides management interfaces for:
  ScheduledReport — view/edit recurring report configurations
  ReportExport    — read-only audit trail of generated reports
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import ReportExport, ScheduledReport


@admin.register(ScheduledReport)
class ScheduledReportAdmin(admin.ModelAdmin):
    """Admin for recurring report configurations."""

    list_display = [
        "name", "store", "report_type_badge", "frequency_badge",
        "recipient_count", "is_enabled", "last_sent_at", "next_send_at",
    ]
    list_filter  = ["report_type", "frequency", "is_enabled", "store"]
    search_fields = ["name", "store__name", "organisation__name"]
    readonly_fields = ["created_at", "updated_at", "last_sent_at", "next_send_at"]
    list_editable = ["is_enabled"]

    fieldsets = [
        ("Report", {
            "fields": ["name", "report_type", "date_range_preset"],
        }),
        ("Schedule", {
            "fields": ["frequency", "is_enabled", "next_send_at", "last_sent_at"],
        }),
        ("Recipients", {
            "fields": ["recipients"],
            "description": "JSON list of email addresses, e.g. ['user@example.com']",
        }),
        ("Ownership", {
            "fields": ["store", "organisation", "created_by"],
            "classes": ["collapse"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]

    @admin.display(description="Report type")
    def report_type_badge(self, obj):
        colors = {
            "sales":     "#3b82f6",
            "inventory": "#10b981",
            "tax":       "#f59e0b",
            "credit":    "#ef4444",
        }
        color = colors.get(obj.report_type, "#6b7280")
        return format_html(
            '<span style="padding:2px 8px;border-radius:4px;'
            'background:{}22;color:{};font-size:11px">{}</span>',
            color, color, obj.get_report_type_display(),
        )

    @admin.display(description="Frequency")
    def frequency_badge(self, obj):
        colors = {
            "daily":   "#3b82f6",
            "weekly":  "#10b981",
            "monthly": "#f59e0b",
        }
        color = colors.get(obj.frequency, "#6b7280")
        return format_html(
            '<span style="padding:2px 8px;border-radius:4px;'
            'background:{}22;color:{};font-size:11px">{}</span>',
            color, color, obj.get_frequency_display(),
        )

    @admin.display(description="Recipients")
    def recipient_count(self, obj):
        n = obj.recipient_count
        return f"{n} address{'es' if n != 1 else ''}"


@admin.register(ReportExport)
class ReportExportAdmin(admin.ModelAdmin):
    """
    Read-only audit trail for generated report exports.

    Exports should not be edited via admin — they are immutable records.
    """

    list_display  = [
        "name", "store", "report_type_badge", "format_badge",
        "period_label", "file_size_display", "created_by", "created_at",
    ]
    list_filter   = ["report_type", "format", "store"]
    search_fields = ["name", "store__name", "period_label"]
    readonly_fields = [
        "store", "organisation", "created_by",
        "report_type", "name", "period_label",
        "date_from", "date_to", "format",
        "file_size_bytes", "file_size_display",
        "scheduled_report", "created_at", "updated_at",
    ]

    def has_add_permission(self, request):
        """Exports are created via the API, not via admin."""
        return False

    def has_change_permission(self, request, obj=None):
        """Exports are immutable audit records."""
        return False

    @admin.display(description="Report type")
    def report_type_badge(self, obj):
        colors = {
            "sales":     "#3b82f6",
            "inventory": "#10b981",
            "tax":       "#f59e0b",
            "credit":    "#ef4444",
        }
        color = colors.get(obj.report_type, "#6b7280")
        return format_html(
            '<span style="padding:2px 8px;border-radius:4px;'
            'background:{}22;color:{};font-size:11px">{}</span>',
            color, color, obj.get_report_type_display(),
        )

    @admin.display(description="Format")
    def format_badge(self, obj):
        color = "#10b981" if obj.format == "csv" else "#ef4444"
        return format_html(
            '<span style="padding:2px 8px;border-radius:4px;'
            'background:{}22;color:{};font-size:11px">{}</span>',
            color, color, obj.format.upper(),
        )

    @admin.display(description="Size")
    def file_size_display(self, obj):
        return obj.file_size_display
