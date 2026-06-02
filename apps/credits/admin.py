"""
apps/credits/admin.py

Django Admin for the credits ("madeni") app.

Provides:
  - CreditTabAdmin: Tabular view of all credit tabs with status badges and aging
  - CreditPaymentAdmin: Payment history with method and reference
  - CreditMessageAdmin: Communication log (WhatsApp/call/SMS)
  - CreditNoteAdmin: Internal staff notes

All tabs and payments are immutable in admin (data integrity — use API for changes).
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import CreditMessage, CreditNote, CreditPayment, CreditTab


# ── Inline classes ────────────────────────────────────────────────────────────

class CreditPaymentInline(admin.TabularInline):
    """Show payments inline when viewing a credit tab detail."""
    model   = CreditPayment
    extra   = 0
    fk_name = "customer"
    fields  = ["created_at", "amount", "method", "reference", "cashier", "note"]
    readonly_fields = ["created_at", "amount", "method", "reference", "cashier"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class CreditMessageInline(admin.TabularInline):
    """Show the last few messages inline on the customer credit view."""
    model  = CreditMessage
    extra  = 0
    fk_name = "customer"
    fields = ["created_at", "kind", "direction", "body", "who"]
    readonly_fields = fields
    can_delete = False
    max_num    = 10

    def has_add_permission(self, request, obj=None):
        return False


# ── Main admins ───────────────────────────────────────────────────────────────

@admin.register(CreditTab)
class CreditTabAdmin(admin.ModelAdmin):
    """
    Admin view for credit tabs.

    Gives a full list of all credit sales, sortable by due date and status.
    All fields are read-only (tabs are created by the POS, edited via API only).
    """

    list_display = [
        "tab_id_display", "customer", "store",
        "amount_display", "amount_paid_display", "balance_display",
        "status_display", "due_date", "is_overdue_display",
        "cashier", "created_at",
    ]
    list_display_links = ["tab_id_display"]
    list_filter = ["status", "store", "due_date"]
    search_fields = ["customer__name", "customer__phone", "transaction__txn_number"]
    list_select_related = ["customer", "store", "cashier", "transaction"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    readonly_fields = [
        "id", "customer", "transaction", "store",
        "amount", "amount_paid", "status", "due_date",
        "cashier", "till_number", "created_at", "updated_at",
    ]

    fieldsets = [
        ("Credit Tab", {
            "fields": ["id", "customer", "transaction", "store", "status", "due_date"],
        }),
        ("Amounts", {
            "fields": ["amount", "amount_paid"],
        }),
        ("Staff", {
            "fields": ["cashier", "till_number"],
        }),
        ("Write-off", {
            "fields": ["write_off_reason"],
            "classes": ["collapse"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]

    def has_add_permission(self, request):
        """Tabs are created via POS only."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Tabs must not be deleted (audit trail)."""
        return False

    # ── Custom display helpers ─────────────────────────────────────────────────

    def tab_id_display(self, obj):
        txn = obj.txn_number
        return f"Tab #{str(obj.id)[:8]} ({txn})"
    tab_id_display.short_description = "Tab"

    def amount_display(self, obj):
        return f"TZS {obj.amount:,}"
    amount_display.short_description = "Amount"

    def amount_paid_display(self, obj):
        return f"TZS {obj.amount_paid:,}"
    amount_paid_display.short_description = "Paid"

    def balance_display(self, obj):
        bal = obj.balance
        color = "#ef4444" if bal > 0 else "#22c55e"
        return format_html('<span style="color:{};font-weight:600">TZS {:,}</span>', color, bal)
    balance_display.short_description = "Balance"

    def status_display(self, obj):
        colors = {
            "open":           ("#ef4444", "#fef2f2"),
            "partially_paid": ("#f59e0b", "#fffbeb"),
            "settled":        ("#22c55e", "#f0fdf4"),
            "written_off":    ("#94a3b8", "#f8fafc"),
        }
        fg, bg = colors.get(obj.status, ("#64748b", "#f1f5f9"))
        return format_html(
            '<span style="color:{};background:{};padding:2px 8px;border-radius:999px;font-size:11px">{}</span>',
            fg, bg, obj.get_status_display(),
        )
    status_display.short_description = "Status"
    status_display.admin_order_field = "status"

    def is_overdue_display(self, obj):
        if obj.is_overdue:
            return format_html('<span style="color:#ef4444;font-weight:600">⚠ Overdue</span>')
        return "—"
    is_overdue_display.short_description = "Overdue?"


@admin.register(CreditPayment)
class CreditPaymentAdmin(admin.ModelAdmin):
    """Admin view for credit payments — read-only audit log."""

    list_display = [
        "id_short", "customer", "store",
        "amount_display", "method", "reference",
        "cashier", "note_preview", "created_at",
    ]
    list_filter = ["method", "store"]
    search_fields = ["customer__name", "customer__phone", "reference"]
    list_select_related = ["customer", "store", "cashier"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    readonly_fields = [
        "id", "customer", "store", "amount", "method",
        "reference", "cashier", "note", "created_at",
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

    def note_preview(self, obj):
        if obj.note:
            return obj.note[:60] + ("…" if len(obj.note) > 60 else "")
        return "—"
    note_preview.short_description = "Note"


@admin.register(CreditMessage)
class CreditMessageAdmin(admin.ModelAdmin):
    """Admin view for credit communication log."""

    list_display = [
        "id_short", "customer", "kind", "direction_display",
        "who", "body_preview", "created_at",
    ]
    list_filter = ["kind", "direction", "store"]
    search_fields = ["customer__name", "body", "who"]
    list_select_related = ["customer", "store", "sent_by"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    readonly_fields = [
        "id", "customer", "store", "kind", "direction",
        "body", "who", "sent_by", "created_at",
    ]

    def has_add_permission(self, request):
        return False

    def id_short(self, obj):
        return str(obj.id)[:8]
    id_short.short_description = "ID"

    def direction_display(self, obj):
        if obj.direction == "in":
            return format_html('<span style="color:#6366f1">← In</span>')
        return format_html('<span style="color:#22c55e">→ Out</span>')
    direction_display.short_description = "Direction"

    def body_preview(self, obj):
        return obj.body[:80] + ("…" if len(obj.body) > 80 else "")
    body_preview.short_description = "Body"


@admin.register(CreditNote)
class CreditNoteAdmin(admin.ModelAdmin):
    """Admin view for internal credit notes."""

    list_display = ["id_short", "customer", "by", "body_preview", "created_at"]
    list_filter = ["store"]
    search_fields = ["customer__name", "body", "by__username"]
    list_select_related = ["customer", "store", "by"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    readonly_fields = ["id", "customer", "store", "by", "created_at"]

    def has_add_permission(self, request):
        return False

    def id_short(self, obj):
        return str(obj.id)[:8]
    id_short.short_description = "ID"

    def body_preview(self, obj):
        return obj.body[:100] + ("…" if len(obj.body) > 100 else "")
    body_preview.short_description = "Note"
