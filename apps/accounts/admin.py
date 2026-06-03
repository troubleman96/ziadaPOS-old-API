"""
apps/accounts/admin.py

Django Admin for accounts: organisations, stores, users, AI credits.

User admin quick-actions (select users on the list → Action dropdown):
  ✓ Activate trial          → status=trial,   7 days,  10,000 TZS
  ✓ Approve Monthly plan    → status=active,  30 days,  25,000 TZS
  ✓ Approve 6-Month plan    → status=active, 180 days, 138,000 TZS
  ✓ Approve Yearly plan     → status=active, 365 days, 264,000 TZS
  ✗ Delete owner + all data → wipes org, stores, inventory, transactions, credits, etc.
"""

import logging
from datetime import timedelta

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db import transaction
from django.utils import timezone
from django.utils.html import format_html

from .models import AICredit, Organisation, Store, User

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _activate_subscription(user, status, days, amount, plan_slug=None, request=None):
    """
    Create or update the user's organisation subscription.
    Returns (subscription, error_message).
    """
    from apps.subscriptions.models import Subscription, SubscriptionPlan

    org = user.get_organisation
    if not org:
        return None, f"{user.phone} has no organisation."

    today = timezone.now().date()

    plan = None
    if plan_slug:
        plan = SubscriptionPlan.objects.filter(slug=plan_slug, is_active=True).first()
        if not plan:
            return None, f"Plan '{plan_slug}' not found or inactive."

    # Get existing pending/trial subscription or create a new one
    sub = org.subscriptions.order_by("-created_at").first()

    with transaction.atomic():
        if sub:
            sub.status       = status
            sub.start_date   = today
            sub.end_date     = today + timedelta(days=days)
            sub.amount_paid  = amount
            sub.payment_date = today
            sub.plan         = plan
            if request:
                sub.activated_by = request.user
            sub.save()
        else:
            sub = Subscription.objects.create(
                organisation  = org,
                status        = status,
                start_date    = today,
                end_date      = today + timedelta(days=days),
                is_trial      = (status == Subscription.STATUS_TRIAL),
                trial_fee     = 10_000,
                amount_paid   = amount,
                payment_date  = today,
                plan          = plan,
                activated_by  = request.user if request else None,
            )

        # Sync org plan label
        org.plan = "pro" if status == Subscription.STATUS_ACTIVE else "free"
        org.save(update_fields=["plan", "updated_at"])

    return sub, None


def _delete_owner_with_cascade(user):
    """
    Hard-delete an owner and ALL associated organisation data.

    Deletion order handles PROTECT FK relationships in credits:
      1. CreditPayment  (PROTECT → Customer)
      2. CreditTab      (PROTECT → Customer)
      3. Organisation   (CASCADE → stores, inventory, transactions, subscriptions, etc.)
      4. User
    """
    with transaction.atomic():
        org = user.get_organisation
        if org:
            store_ids = list(org.stores.values_list("id", flat=True))
            if store_ids:
                try:
                    from apps.credits.models import CreditPayment, CreditTab
                    CreditPayment.objects.filter(store_id__in=store_ids).delete()
                    CreditTab.objects.filter(store_id__in=store_ids).delete()
                except Exception:
                    pass
            org.delete()   # CASCADE deletes all remaining related data
        user.delete()


# ── User quick-action admin actions ───────────────────────────────────────────

@admin.action(description="✓ Activate 7-day trial (10,000 TZS)")
def action_activate_trial(modeladmin, request, queryset):
    ok, fail = 0, []
    for user in queryset.filter(role=User.ROLE_OWNER):
        _, err = _activate_subscription(
            user, status="trial", days=7, amount=10_000, request=request,
        )
        if err:
            fail.append(err)
        else:
            ok += 1
            logger.info("Admin %s activated trial for %s", request.user.phone, user.phone)
    if ok:
        modeladmin.message_user(request, f"✓ Trial activated for {ok} account(s).", messages.SUCCESS)
    for e in fail:
        modeladmin.message_user(request, e, messages.ERROR)


@admin.action(description="✓ Approve Monthly plan (25,000 TZS / 30 days)")
def action_approve_monthly(modeladmin, request, queryset):
    ok, fail = 0, []
    for user in queryset.filter(role=User.ROLE_OWNER):
        _, err = _activate_subscription(
            user, status="active", days=30, amount=25_000,
            plan_slug="monthly", request=request,
        )
        if err:
            fail.append(err)
        else:
            ok += 1
            logger.info("Admin %s approved monthly plan for %s", request.user.phone, user.phone)
    if ok:
        modeladmin.message_user(request, f"✓ Monthly plan approved for {ok} account(s).", messages.SUCCESS)
    for e in fail:
        modeladmin.message_user(request, e, messages.ERROR)


@admin.action(description="✓ Approve 6-Month plan (138,000 TZS / 180 days)")
def action_approve_6month(modeladmin, request, queryset):
    ok, fail = 0, []
    for user in queryset.filter(role=User.ROLE_OWNER):
        _, err = _activate_subscription(
            user, status="active", days=180, amount=138_000,
            plan_slug="half-yearly", request=request,
        )
        if err:
            fail.append(err)
        else:
            ok += 1
            logger.info("Admin %s approved 6-month plan for %s", request.user.phone, user.phone)
    if ok:
        modeladmin.message_user(request, f"✓ 6-Month plan approved for {ok} account(s).", messages.SUCCESS)
    for e in fail:
        modeladmin.message_user(request, e, messages.ERROR)


@admin.action(description="✓ Approve Yearly plan (264,000 TZS / 365 days)")
def action_approve_yearly(modeladmin, request, queryset):
    ok, fail = 0, []
    for user in queryset.filter(role=User.ROLE_OWNER):
        _, err = _activate_subscription(
            user, status="active", days=365, amount=264_000,
            plan_slug="yearly", request=request,
        )
        if err:
            fail.append(err)
        else:
            ok += 1
            logger.info("Admin %s approved yearly plan for %s", request.user.phone, user.phone)
    if ok:
        modeladmin.message_user(request, f"✓ Yearly plan approved for {ok} account(s).", messages.SUCCESS)
    for e in fail:
        modeladmin.message_user(request, e, messages.ERROR)


@admin.action(description="✗ DELETE owner + all organisation data (irreversible)")
def action_delete_owner_cascade(modeladmin, request, queryset):
    deleted, fail = 0, []
    for user in queryset.filter(role=User.ROLE_OWNER):
        try:
            phone = user.phone
            name  = user.full_name
            _delete_owner_with_cascade(user)
            deleted += 1
            logger.warning(
                "Admin %s hard-deleted owner %s (%s) and all their data.",
                request.user.phone, phone, name,
            )
        except Exception as exc:
            fail.append(f"{user.phone}: {exc}")
    if deleted:
        modeladmin.message_user(
            request,
            f"✗ {deleted} owner(s) and all their data permanently deleted.",
            messages.WARNING,
        )
    for e in fail:
        modeladmin.message_user(request, e, messages.ERROR)


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
        colors = {"pharmacy": "#10b981", "retail": "#3b82f6", "wholesale": "#f59e0b"}
        color = colors.get(obj.business_type, "#6b7280")
        labels = {"pharmacy": "Pharmacy", "retail": "Retail", "wholesale": "Wholesale"}
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
        "organisation", "store", "sub_status_display",
        "is_phone_verified", "employment_status", "is_active", "date_joined",
    ]
    list_filter = [
        "role", "is_active", "employment_status",
        "is_phone_verified", "is_email_verified",
        "store__organisation",
    ]
    search_fields = ["phone", "first_name", "last_name", "email"]
    list_select_related = ["store", "store__organisation", "organisation"]
    ordering = ["-date_joined"]

    actions = [
        action_activate_trial,
        action_approve_monthly,
        action_approve_6month,
        action_approve_yearly,
        action_delete_owner_cascade,
    ]

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

    def sub_status_display(self, obj):
        if obj.role != User.ROLE_OWNER:
            return "—"
        org = obj.get_organisation
        if not org:
            return "—"
        sub = org.subscriptions.order_by("-created_at").first()
        if not sub:
            return format_html('<span style="color:#6b7280;font-size:11px">No subscription</span>')
        colors = {
            "trial":           "#f59e0b",
            "active":          "#10b981",
            "expired":         "#ef4444",
            "cancelled":       "#6b7280",
            "pending_payment": "#3b82f6",
        }
        color = colors.get(sub.status, "#6b7280")
        label = sub.get_status_display()
        days  = sub.days_remaining
        return format_html(
            '<span style="padding:2px 8px;border-radius:4px;background:{}22;color:{};font-size:11px">'
            '{}</span> <small style="color:#888">{} days</small>',
            color, color, label, days,
        )
    sub_status_display.short_description = "Subscription"

    def delete_queryset(self, request, queryset):
        """Override bulk delete to fully cascade org data for owner-role users."""
        for user in queryset:
            if user.role == User.ROLE_OWNER:
                _delete_owner_with_cascade(user)
            else:
                user.delete()


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
