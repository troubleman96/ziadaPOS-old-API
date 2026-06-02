"""
apps/transactions/admin.py

Django Admin for Transactions and Transaction Lines.
Provides a complete view of all sales, with inline line items.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import Transaction, TransactionLine


class TransactionLineInline(admin.TabularInline):
    """
    Inline display of line items within a transaction detail.
    Shows product, qty, price, cost, and line total.
    """
    model = TransactionLine
    extra = 0  # Don't show empty rows for adding lines (done via POS)
    readonly_fields = [
        "product", "product_name", "product_sku",
        "unit_price", "unit_cost", "qty",
        "line_total_display", "line_profit_display",
    ]
    # Prevent adding/deleting lines from admin (data integrity)
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def line_total_display(self, obj):
        return f"TZS {obj.line_total:,}"
    line_total_display.short_description = "Line Total"

    def line_profit_display(self, obj):
        profit = obj.line_profit
        color = "#22c55e" if profit >= 0 else "#ef4444"
        return format_html('<span style="color:{}">TZS {:,}</span>', color, profit)
    line_profit_display.short_description = "Profit"


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """
    Admin view for transactions with inline line items.
    All transactions are read-only in admin (they are created via the POS API).
    """

    list_display = [
        "txn_number", "store", "created_at_display",
        "customer_name", "payment_method", "status_display",
        "total_display", "profit_display",
        "cashier", "till_number",
    ]
    list_display_links = ["txn_number"]
    list_filter = ["status", "payment_method", "store", "created_at"]
    search_fields = ["txn_number", "customer_name", "customer_phone", "payment_reference"]
    list_select_related = ["store", "cashier", "customer"]
    date_hierarchy = "created_at"

    # Inline line items
    inlines = [TransactionLineInline]

    # Read-only fields (transactions should not be edited in admin)
    readonly_fields = [
        "id", "txn_number", "store", "created_at",
        "payment_method", "payment_reference", "status",
        "subtotal", "discount_pct", "discount_amount", "tax_amount",
        "total", "cost_total", "profit",
        "cashier", "till_number",
        "customer_name", "customer_phone", "customer",
        "channel", "notes",
    ]

    fieldsets = [
        ("Reference", {
            "fields": ["id", "txn_number", "store", "channel", "created_at"],
        }),
        ("Customer", {
            "fields": ["customer", "customer_name", "customer_phone"],
        }),
        ("Payment", {
            "fields": ["payment_method", "payment_reference", "status"],
        }),
        ("Amounts (TZS)", {
            "fields": [
                "subtotal", "discount_pct", "discount_amount",
                "tax_amount", "total", "cost_total", "profit",
            ],
        }),
        ("Staff / Register", {
            "fields": ["cashier", "till_number"],
        }),
        ("Notes", {
            "fields": ["notes"],
            "classes": ["collapse"],
        }),
    ]

    def has_add_permission(self, request):
        """Transactions are created via POS only."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Transactions must not be deleted (audit trail)."""
        return False

    # ── Custom display columns ─────────────────────────────────────────────────

    def created_at_display(self, obj):
        return obj.created_at.strftime("%d %b %Y %H:%M")
    created_at_display.short_description = "Date / Time"
    created_at_display.admin_order_field = "created_at"

    def status_display(self, obj):
        colors = {
            "paid":     "#22c55e",
            "credit":   "#f59e0b",
            "refunded": "#ef4444",
            "void":     "#999",
        }
        color = colors.get(obj.status, "#999")
        return format_html(
            '<span style="color: {}; font-weight: 600; text-transform: capitalize;">{}</span>',
            color, obj.status,
        )
    status_display.short_description = "Status"

    def total_display(self, obj):
        return f"TZS {obj.total:,}"
    total_display.short_description = "Total"

    def profit_display(self, obj):
        color = "#22c55e" if obj.profit >= 0 else "#ef4444"
        return format_html('<span style="color:{}">TZS {:,}</span>', color, obj.profit)
    profit_display.short_description = "Profit"
