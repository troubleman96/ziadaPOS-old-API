"""
apps/inventory/admin.py

Django Admin for inventory: Products, Categories, StockAdjustments.
Supplier admin lives in apps.suppliers.admin.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import Category, Product, StockAdjustment


# ── Category ──────────────────────────────────────────────────────────────────

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin for product categories."""

    list_display = ["name", "product_count", "sort_order", "created_at"]
    list_editable = ["sort_order"]
    search_fields = ["name"]
    readonly_fields = ["id", "created_at", "updated_at"]

    def product_count(self, obj):
        return obj.products.filter(is_active=True).count()

    product_count.short_description = "Products"


# ── Product ───────────────────────────────────────────────────────────────────

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """
    Admin for products — the core inventory view.
    Colour-codes stock status for quick scanning.
    """

    list_display = [
        "name", "sku", "category", "supplier",
        "price_display", "cost_display", "margin_display",
        "stock_display", "stock_status_display",
        "is_active", "updated_at",
    ]
    list_display_links = ["name"]
    list_filter = ["is_active", "category", "store", "supplier"]
    search_fields = ["name", "sku", "barcode"]
    list_select_related = ["category", "supplier", "store"]
    readonly_fields = [
        "id", "created_at", "updated_at",
        "margin_pct", "stock_status", "days_of_stock",
    ]

    # Group fields logically in the detail form
    fieldsets = [
        ("Identity", {
            "fields": ["id", "store", "name", "sku", "barcode", "color"],
        }),
        ("Classification", {
            "fields": ["category", "supplier", "unit"],
        }),
        ("Pricing (TZS)", {
            "fields": ["price", "cost", "margin_pct"],
            "description": "All prices in TZS (integers). margin_pct is read-only.",
        }),
        ("Stock Levels", {
            "fields": ["stock", "min_stock", "max_stock", "weekly_sold", "last_restock_at"],
        }),
        ("Computed", {
            "fields": ["stock_status", "days_of_stock"],
            "classes": ["collapse"],
        }),
        ("Status", {
            "fields": ["is_active"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]

    # ── Custom list display columns ────────────────────────────────────────────

    def price_display(self, obj):
        return f"TZS {obj.price:,}"
    price_display.short_description = "Price"

    def cost_display(self, obj):
        return f"TZS {obj.cost:,}"
    cost_display.short_description = "Cost"

    def margin_display(self, obj):
        """Show margin with green/red colour depending on value."""
        pct = obj.margin_pct
        color = "#22c55e" if pct >= 20 else "#f59e0b" if pct >= 10 else "#ef4444"
        return format_html('<span style="color: {}; font-weight: 600;">{:.0f}%</span>', color, pct)
    margin_display.short_description = "Margin"

    def stock_display(self, obj):
        """Show stock with quantity and reorder point."""
        return format_html("{} <small style='color:#999'>/ {}</small>", obj.stock, obj.min_stock)
    stock_display.short_description = "Stock / Min"

    def stock_status_display(self, obj):
        """Colour-coded stock status badge."""
        status = obj.stock_status
        colors = {
            "active":   ("#22c55e", "Active"),
            "low":      ("#f59e0b", "Low"),
            "critical": ("#ef4444", "Critical"),
            "out":      ("#991b1b", "Out"),
        }
        color, label = colors.get(status, ("#999", status))
        return format_html(
            '<span style="color: {}; font-weight: 600;">● {}</span>',
            color, label,
        )
    stock_status_display.short_description = "Status"


# ── Stock Adjustment ──────────────────────────────────────────────────────────

@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    """
    Admin for stock movement audit trail.
    This is read-only — adjustments are created programmatically.
    """

    list_display = [
        "product", "adjustment_type", "quantity_change_display",
        "quantity_before", "quantity_after",
        "reference", "performed_by", "created_at",
    ]
    list_filter = ["adjustment_type", "product__store", "created_at"]
    search_fields = ["product__name", "product__sku", "reference", "note"]
    list_select_related = ["product", "performed_by"]
    readonly_fields = [
        "id", "product", "adjustment_type",
        "quantity_change", "quantity_before", "quantity_after",
        "reference", "performed_by", "note",
        "created_at", "updated_at",
    ]

    # Prevent accidental manual creation/deletion of audit records
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def quantity_change_display(self, obj):
        """Show change with +/- colour coding."""
        if obj.quantity_change >= 0:
            return format_html('<span style="color:#22c55e">+{}</span>', obj.quantity_change)
        return format_html('<span style="color:#ef4444">{}</span>', obj.quantity_change)
    quantity_change_display.short_description = "Change"
