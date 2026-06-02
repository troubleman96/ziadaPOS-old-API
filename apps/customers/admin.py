"""
apps/customers/admin.py

Django Admin for Customer management.
Provides a searchable, filterable list of all customers with
segment tags, credit balance warnings, and spend statistics.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """
    Admin view for registered customers.

    Lets store managers:
      - View, search, and filter the full customer list
      - Edit contact details and segment
      - See credit balance warnings at a glance
    """

    list_display = [
        "name", "store", "phone_display",
        "segment_display", "total_spent_display",
        "open_credit_display", "last_visit", "is_active",
    ]
    list_display_links = ["name"]
    list_filter = ["segment", "is_active", "store"]
    search_fields = ["name", "phone", "email"]
    list_select_related = ["store"]
    date_hierarchy = None  # Not date-based primarily
    ordering = ["-total_spent"]

    fieldsets = [
        ("Identity", {
            "fields": ["store", "name", "phone", "email", "avatar_hue", "is_active"],
        }),
        ("Segment", {
            "fields": ["segment"],
            "description": "VIP: >1M TZS lifetime spend. Regular: >200k. New: <60 days.",
        }),
        ("Stats (cached)", {
            "fields": ["total_spent", "last_visit", "avg_ticket", "open_credit"],
            "description": "These fields are updated automatically when transactions are recorded.",
            "classes": ["collapse"],
        }),
        ("Notes", {
            "fields": ["notes"],
            "classes": ["collapse"],
        }),
    ]

    # Allow editing segment and contact details, but protect stats
    readonly_fields = ["id", "total_spent", "last_visit", "avg_ticket", "open_credit"]

    # ── Custom display columns ─────────────────────────────────────────────────

    def phone_display(self, obj):
        """Show phone with a clickable tel: link."""
        if obj.phone:
            return format_html('<a href="tel:{}">{}</a>', obj.phone, obj.phone)
        return format_html('<span style="color:#999">—</span>')
    phone_display.short_description = "Phone"

    def segment_display(self, obj):
        """Colour-coded segment pill."""
        colors = {
            "VIP":        ("#f59e0b", "#fef3c7"),
            "Regular":    ("#6366f1", "#eef2ff"),
            "Occasional": ("#64748b", "#f1f5f9"),
            "New":        ("#10b981", "#d1fae5"),
        }
        fg, bg = colors.get(obj.segment, ("#64748b", "#f1f5f9"))
        return format_html(
            '<span style="color:{};background:{};padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600">{}</span>',
            fg, bg, obj.segment,
        )
    segment_display.short_description = "Segment"
    segment_display.admin_order_field = "segment"

    def total_spent_display(self, obj):
        """Format total_spent as 'TZS 1,234,000'."""
        return f"TZS {obj.total_spent:,}"
    total_spent_display.short_description = "Total Spent"
    total_spent_display.admin_order_field = "total_spent"

    def open_credit_display(self, obj):
        """Highlight non-zero credit in amber."""
        if obj.open_credit > 0:
            return format_html(
                '<span style="color:#f59e0b;font-weight:600">TZS {:,}</span>',
                obj.open_credit,
            )
        return format_html('<span style="color:#999">—</span>')
    open_credit_display.short_description = "Open Credit"
    open_credit_display.admin_order_field = "open_credit"
