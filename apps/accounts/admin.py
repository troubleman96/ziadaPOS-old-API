"""
apps/accounts/admin.py

Django Admin for accounts: organisations, stores, users, AI credits.
All new fields (phone, business_type, region, max_stores, verifications) included.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.html import format_html

from .models import AICredit, Organisation, Store, User


# ── Organisation ──────────────────────────────────────────────────────────────

@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):

    list_display = [
        "name", "business_type_badge", "region", "plan_badge",
        "store_count", "max_stores", "owner_link",
        "has_active_sub_display", "created_at",
    ]
    list_display_links = ["name"]
    list_filter   = ["plan", "business_type", "region", "created_at"]
    search_fields = ["name", "legal_name", "tin"]
    readonly_fields = [
        "id", "created_at", "updated_at",
        "active_subscription_display",
    ]

    fieldsets = [
        ("Identity", {
            "fields": ["id", "name", "legal_name", "tin", "country", "currency"],
        }),
        ("Tanzania Business", {
            "fields": ["business_type", "region"],
        }),
        ("Plan & Stores", {
            "fields": ["plan", "max_stores", "trial_ends_at", "active_subscription_display"],
        }),
        ("AI Credits", {
            "fields": ["ai_credits_monthly"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]

    def store_count(self, obj):
        count = obj.stores.filter(is_active=True).count()
        return format_html(
            '<a href="/admin/accounts/store/?organisation__id__exact={}">{}/{}</a>',
            obj.id, count, obj.max_stores,
        )
    store_count.short_description = "Stores (active/max)"

    def owner_link(self, obj):
        owner = obj.members.filter(role="owner").first()
        if owner:
            return format_html(
                '<a href="/admin/accounts/user/{}/change/">{}</a>',
                owner.pk, owner.phone,
            )
        return "—"
    owner_link.short_description = "Owner"

    def business_type_badge(self, obj):
        colors = {
            "pharmacy":  "#10b981",
            "retail":    "#3b82f6",
            "wholesale": "#f59e0b",
        }
        color = colors.get(obj.business_type, "#6b7280")
        labels = {
            "pharmacy":  "Pharmacy",
            "retail":    "Retail",
            "wholesale": "Wholesale",
        }
        label = labels.get(obj.business_type, obj.business_type or "—")
        return format_html(
            '<span style="padding:2px 8px;border-radius:4px;background:{}22;color:{};font-size:11px">{}</span>',
            color, color, label,
        )
    business_type_badge.short_description = "Business Type"

    def plan_badge(self, obj):
        colors = {"free": "#6b7280", "pro": "#3b82f6", "enterprise": "#8b5cf6"}
        color  = colors.get(obj.plan, "#6b7280")
        return format_html(
            '<span style="padding:2px 8px;border-radius:4px;background:{}22;color:{};font-size:11px">{}</span>',
            color, color, obj.plan.title(),
        )
    plan_badge.short_description = "Plan"

    def has_active_sub_display(self, obj):
        if obj.has_active_subscription:
            return format_html('<span style="color:#10b981;font-weight:600">✓ Active</span>')
        return format_html('<span style="color:#ef4444">✗ Inactive</span>')
    has_active_sub_display.short_description = "Sub Active"

    def active_subscription_display(self, obj):
        sub = obj.active_subscription
        if not sub:
            return "No active subscription"
        return format_html(
            '{} — {} → {} ({} days remaining)',
            sub.get_status_display(), sub.start_date, sub.end_date, sub.days_remaining,
        )
    active_subscription_display.short_description = "Current Subscription"


# ── Store ─────────────────────────────────────────────────────────────────────

@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):

    list_display = [
        "name", "organisation", "area", "status_badge",
        "till_count", "is_main_store", "is_active",
        "staff_count_display", "created_at",
    ]
    list_display_links = ["name"]
    list_filter  = ["is_active", "status", "is_main_store", "organisation"]
    search_fields = ["name", "area", "code", "phone"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["organisation"]

    fieldsets = [
        ("Identity", {
            "fields": ["id", "organisation", "name", "code", "is_main_store"],
        }),
        ("Location & Contact", {
            "fields": ["address", "area", "phone", "email"],
        }),
        ("Operations", {
            "fields": ["till_count", "open_hours", "color", "status", "is_active"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]

    def status_badge(self, obj):
        colors = {"open": "#10b981", "closed": "#6b7280", "paused": "#f59e0b"}
        color  = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="padding:2px 8px;border-radius:4px;background:{}22;color:{};font-size:11px">● {}</span>',
            color, color, obj.status.title(),
        )
    status_badge.short_description = "Status"

    def staff_count_display(self, obj):
        count = obj.staff.filter(is_active=True).count()
        return format_html(
            '<a href="/admin/accounts/user/?store__id__exact={}">{} staff</a>',
            obj.id, count,
        )
    staff_count_display.short_description = "Staff"


# ── User ──────────────────────────────────────────────────────────────────────

@admin.register(User)
class UserAdmin(DjangoUserAdmin):

    list_display = [
        "phone", "full_name_display", "role_badge",
        "organisation", "store",
        "is_phone_verified", "is_email_verified",
        "employment_status", "is_active", "date_joined",
    ]
    list_filter = [
        "role", "is_active", "employment_status",
        "is_phone_verified", "is_email_verified",
        "store__organisation",
    ]
    search_fields = ["phone", "first_name", "last_name", "email"]
    list_select_related = ["store", "store__organisation", "organisation"]
    ordering = ["-date_joined"]

    # Override default fieldsets to include phone-based fields
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Ziada Profile", {
            "fields": [
                "phone", "role", "organisation", "store",
                "avatar_hue", "shift", "employment_status",
            ],
        }),
        ("Verification Status", {
            "fields": ["is_phone_verified", "is_email_verified"],
        }),
        ("POS Permissions", {
            "fields": ["pin", "can_refund", "can_discount", "can_view_reports"],
        }),
    )

    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("Ziada Profile", {
            "fields": ["first_name", "last_name", "phone", "role", "organisation", "store"],
        }),
    )

    readonly_fields = ["date_joined", "last_login"]

    def full_name_display(self, obj):
        return obj.full_name
    full_name_display.short_description = "Full Name"

    def role_badge(self, obj):
        colors = {"admin": "#ef4444", "owner": "#3b82f6", "staff": "#10b981"}
        color  = colors.get(obj.role, "#6b7280")
        return format_html(
            '<span style="padding:2px 8px;border-radius:4px;background:{}22;color:{};font-size:11px">{}</span>',
            color, color, obj.role.title(),
        )
    role_badge.short_description = "Role"


# ── AI Credits ────────────────────────────────────────────────────────────────

@admin.register(AICredit)
class AICreditAdmin(admin.ModelAdmin):

    list_display = [
        "organisation", "year", "month",
        "used_progress_bar", "allocated",
        "percentage_used_display", "remaining_display",
    ]
    list_filter  = ["year", "month", "organisation"]
    search_fields = ["organisation__name"]
    readonly_fields = ["id", "created_at", "updated_at", "remaining", "percentage_used"]
    list_select_related = ["organisation"]

    def used_progress_bar(self, obj):
        pct = obj.percentage_used
        color = "#ef4444" if pct >= 90 else "#f59e0b" if pct >= 70 else "#10b981"
        return format_html(
            '<div style="width:130px;background:#e5e7eb;border-radius:4px;height:10px;display:inline-block">'
            '<div style="width:{:.0f}%;background:{};height:10px;border-radius:4px"></div>'
            '</div> <small style="color:#666">{:,}/{:,}</small>',
            min(pct, 100), color, obj.used, obj.allocated,
        )
    used_progress_bar.short_description = "Used"

    def percentage_used_display(self, obj):
        pct = obj.percentage_used
        color = "#ef4444" if pct >= 90 else "#f59e0b" if pct >= 70 else "#10b981"
        return format_html('<span style="color:{};font-weight:600">{:.1f}%</span>', color, pct)
    percentage_used_display.short_description = "% Used"

    def remaining_display(self, obj):
        return f"{obj.remaining:,}"
    remaining_display.short_description = "Remaining"
