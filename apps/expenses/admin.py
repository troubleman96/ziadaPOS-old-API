from django.contrib import admin
from django.utils.html import format_html

from .models import Expense


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = [
        "id_short", "title", "category_display", "amount_display",
        "payment_method", "recorded_by_name", "store", "created_at",
    ]
    list_display_links = ["id_short"]
    list_filter = ["category", "payment_method", "store"]
    search_fields = ["title", "notes", "payment_reference"]
    list_select_related = ["recorded_by", "store"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    readonly_fields = [
        "id", "store", "title", "category", "amount", "payment_method",
        "payment_reference", "notes", "receipt_url", "recorded_by",
        "created_at", "updated_at",
    ]

    fieldsets = [
        ("Expense", {
            "fields": ["id", "title", "category", "amount", "store"],
        }),
        ("Payment", {
            "fields": ["payment_method", "payment_reference"],
        }),
        ("Details", {
            "fields": ["notes", "receipt_url"],
        }),
        ("Staff", {
            "fields": ["recorded_by"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def id_short(self, obj):
        return str(obj.id)[:8]
    id_short.short_description = "ID"

    def amount_display(self, obj):
        return f"TZS {obj.amount:,}"
    amount_display.short_description = "Amount"
    amount_display.admin_order_field = "amount"

    def category_display(self, obj):
        colors = {
            "Rent": "#6366f1", "Utilities": "#f59e0b", "Salaries": "#10b981",
            "Supplies": "#3b82f6", "Transport": "#8b5cf6", "Marketing": "#ec4899",
            "Maintenance": "#f97316", "Licences & permits": "#14b8a6",
            "Insurance": "#06b6d4", "Other": "#6b7280",
        }
        c = colors.get(obj.category, "#6b7280")
        return format_html(
            '<span style="color:{};background:{}30;padding:2px 8px;border-radius:999px;font-size:11px">{}</span>',
            c, c, obj.category,
        )
    category_display.short_description = "Category"

    def recorded_by_name(self, obj):
        if obj.recorded_by:
            return obj.recorded_by.get_full_name() or obj.recorded_by.username
        return "-"
    recorded_by_name.short_description = "Recorded by"
