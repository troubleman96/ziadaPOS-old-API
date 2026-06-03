"""
apps/subscriptions/admin.py

Django Admin registration for subscription plans and subscriptions.

Cameltech admins use this panel to:
  - Create and price subscription plans
  - View all organisation subscriptions
  - Confirm payments and activate subscriptions
  - Add extra stores to an active subscription
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import Subscription, SubscriptionPlan


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display  = ["name", "price_per_month_display", "duration_months", "total_price_display",
                     "included_stores", "extra_store_price_per_month", "is_active", "sort_order"]
    list_editable = ["is_active", "sort_order"]
    list_filter   = ["is_active"]
    prepopulated_fields = {"slug": ("name",)}

    fieldsets = [
        ("Plan Details", {
            "fields": ["name", "slug", "description", "is_active", "sort_order"],
        }),
        ("Pricing (TZS)", {
            "fields": ["price_per_month", "duration_months", "included_stores",
                       "extra_store_price_per_month"],
            "description": "All amounts in Tanzanian Shillings (TZS). No decimals.",
        }),
    ]

    def price_per_month_display(self, obj):
        return f"{obj.price_per_month:,} TZS"
    price_per_month_display.short_description = "Price/Month"

    def total_price_display(self, obj):
        return f"{obj.total_price:,} TZS"
    total_price_display.short_description = "Total/Cycle"


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display  = ["organisation", "plan", "status_badge", "is_trial",
                     "start_date", "end_date", "days_remaining_display",
                     "amount_paid_display", "extra_stores", "activated_by"]
    list_filter   = ["status", "is_trial", "plan"]
    search_fields = ["organisation__name", "payment_reference"]
    raw_id_fields = ["organisation", "plan", "activated_by"]
    date_hierarchy = "start_date"
    readonly_fields = ["created_at", "updated_at", "total_amount_due_display",
                       "max_stores_allowed_display", "is_active_now_display"]

    fieldsets = [
        ("Organisation", {
            "fields": ["organisation", "plan", "status"],
        }),
        ("Duration", {
            "fields": ["start_date", "end_date", "is_trial", "trial_fee"],
        }),
        ("Stores", {
            "fields": ["extra_stores", "max_stores_allowed_display"],
        }),
        ("Payment", {
            "fields": ["amount_paid", "total_amount_due_display",
                       "payment_reference", "payment_date", "activated_by"],
        }),
        ("Notes & Audit", {
            "fields": ["notes", "created_at", "updated_at", "is_active_now_display"],
        }),
    ]

    def status_badge(self, obj):
        colours = {
            "trial":           "#f59e0b",
            "active":          "#10b981",
            "expired":         "#ef4444",
            "cancelled":       "#6b7280",
            "pending_payment": "#3b82f6",
        }
        colour = colours.get(obj.status, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px">{}</span>',
            colour,
            obj.get_status_display(),
        )
    status_badge.short_description = "Status"

    def days_remaining_display(self, obj):
        return f"{obj.days_remaining}d"
    days_remaining_display.short_description = "Days Left"

    def amount_paid_display(self, obj):
        return f"{obj.amount_paid:,} TZS"
    amount_paid_display.short_description = "Paid"

    def total_amount_due_display(self, obj):
        return f"{obj.total_amount_due:,} TZS"
    total_amount_due_display.short_description = "Total Due"

    def max_stores_allowed_display(self, obj):
        return obj.max_stores_allowed
    max_stores_allowed_display.short_description = "Max Stores Allowed"

    def is_active_now_display(self, obj):
        return "Yes" if obj.is_active_now else "No"
    is_active_now_display.short_description = "Currently Active?"
