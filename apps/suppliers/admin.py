from django.contrib import admin
from django.utils.html import format_html

from .models import Supplier, SupplierDelivery, SupplierPayment


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = [
        "name", "store", "category", "rep", "phone",
        "payment_terms_display", "status_badge",
        "outstanding_display", "product_count_display", "created_at",
    ]
    list_filter  = ["status", "payment_terms", "store"]
    search_fields = ["name", "rep", "phone", "email", "category"]
    readonly_fields = [
        "id", "created_at", "updated_at",
        "outstanding_balance", "pending_invoices_count",
        "last_delivery_date", "product_count",
    ]

    fieldsets = [
        ("Identity", {
            "fields": ["id", "store", "organisation", "name", "category", "status"],
        }),
        ("Contact", {
            "fields": ["rep", "phone", "email", "address"],
        }),
        ("Commercial terms", {
            "fields": ["payment_terms", "notes"],
        }),
        ("Computed (read-only)", {
            "fields": ["outstanding_balance", "pending_invoices_count", "last_delivery_date", "product_count"],
            "classes": ["collapse"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]

    @admin.display(description="Terms")
    def payment_terms_display(self, obj):
        return f"{obj.payment_terms}d"

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            "active":   "#10b981",
            "inactive": "#6b7280",
            "on_hold":  "#f59e0b",
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="padding:2px 8px;border-radius:4px;background:{}22;color:{};font-size:11px">{}</span>',
            color, color, obj.get_status_display(),
        )

    @admin.display(description="Outstanding")
    def outstanding_display(self, obj):
        bal = obj.outstanding_balance
        if bal == 0:
            return format_html('<span style="color:#10b981">Nil</span>')
        return format_html('<span style="color:#ef4444">TZS {:,}</span>', bal)

    @admin.display(description="Products")
    def product_count_display(self, obj):
        return obj.product_count


@admin.register(SupplierDelivery)
class SupplierDeliveryAdmin(admin.ModelAdmin):
    list_display  = [
        "supplier", "invoice_number", "delivery_date",
        "items_count", "value_display", "status", "is_paid", "recorded_by",
    ]
    list_filter   = ["status", "is_paid", "store", "delivery_date"]
    search_fields = ["supplier__name", "invoice_number"]
    list_editable = ["is_paid"]
    readonly_fields = ["id", "created_at", "updated_at"]

    @admin.display(description="Value (TZS)")
    def value_display(self, obj):
        return f"TZS {obj.total_value:,}"


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display  = [
        "supplier", "amount_display", "payment_date",
        "payment_method", "reference", "recorded_by",
    ]
    list_filter   = ["payment_method", "store", "payment_date"]
    search_fields = ["supplier__name", "reference"]
    readonly_fields = ["id", "created_at", "updated_at"]

    def has_change_permission(self, request, obj=None):
        """Payments are immutable ledger entries."""
        return False

    @admin.display(description="Amount (TZS)")
    def amount_display(self, obj):
        return f"TZS {obj.amount:,}"
