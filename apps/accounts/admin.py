"""
apps/accounts/admin.py

Django Admin configuration for accounts models.

Everything is registered here so the admin site works "out of the box"
without any extra setup. Admins can:
  - Create organisations and stores
  - Manage users and their roles
  - Monitor AI credit usage
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.html import format_html

from .models import AICredit, Organisation, Store, User


# ── Organisation ──────────────────────────────────────────────────────────────

@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    """Admin view for managing organisations (businesses)."""

    # Columns shown in the list view
    list_display = ["name", "plan", "tin", "store_count", "ai_credits_monthly", "created_at"]

    # Clickable links in the list view
    list_display_links = ["name"]

    # Allow filtering by plan in the right sidebar
    list_filter = ["plan", "country", "created_at"]

    # Full-text search fields
    search_fields = ["name", "legal_name", "tin"]

    # Read-only in detail view
    readonly_fields = ["id", "created_at", "updated_at"]

    # Field layout in the detail form
    fieldsets = [
        ("Identity", {
            "fields": ["id", "name", "legal_name", "tin", "country", "currency"],
        }),
        ("Plan & Billing", {
            "fields": ["plan", "trial_ends_at", "ai_credits_monthly"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],  # collapsed by default
        }),
    ]

    def store_count(self, obj):
        """Show how many stores this organisation has."""
        count = obj.stores.count()
        return format_html('<a href="/admin/accounts/store/?organisation__id__exact={}">{} stores</a>', obj.id, count)

    store_count.short_description = "Stores"


# ── Store ─────────────────────────────────────────────────────────────────────

@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    """Admin view for managing store locations."""

    list_display = ["name", "organisation", "area", "till_count", "is_active", "created_at"]
    list_display_links = ["name"]
    list_filter = ["is_active", "organisation", "created_at"]
    search_fields = ["name", "area", "code", "phone"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["organisation"]  # avoid N+1 queries

    fieldsets = [
        ("Identity", {
            "fields": ["id", "organisation", "name", "code"],
        }),
        ("Location", {
            "fields": ["address", "area", "phone"],
        }),
        ("Operations", {
            "fields": ["till_count", "is_active"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]


# ── User ──────────────────────────────────────────────────────────────────────

@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """
    Admin view for managing users.
    Extends Django's built-in UserAdmin so we keep all the password management
    functionality and add our custom fields.
    """

    # List view columns
    list_display = [
        "username", "full_name_display", "email", "role",
        "store", "is_active", "date_joined",
    ]
    list_filter = ["role", "is_active", "is_staff", "store__organisation"]
    search_fields = ["username", "first_name", "last_name", "email", "phone"]
    list_select_related = ["store", "store__organisation"]

    # Add our custom fields to the existing fieldsets
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Ziada Profile", {
            "fields": ["role", "store", "phone", "avatar_hue"],
        }),
    )

    # Fields shown when creating a new user
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("Ziada Profile", {
            "fields": ["first_name", "last_name", "role", "store", "phone"],
        }),
    )

    def full_name_display(self, obj):
        """Display full name in list view."""
        return obj.full_name

    full_name_display.short_description = "Full Name"


# ── AI Credits ────────────────────────────────────────────────────────────────

@admin.register(AICredit)
class AICreditAdmin(admin.ModelAdmin):
    """Admin view for monitoring AI credit usage per organisation per month."""

    list_display = [
        "organisation", "year", "month", "used", "allocated",
        "percentage_used_display", "remaining_display",
    ]
    list_filter = ["organisation", "year", "month"]
    search_fields = ["organisation__name"]
    readonly_fields = ["id", "created_at", "updated_at", "percentage_used"]
    list_select_related = ["organisation"]

    def percentage_used_display(self, obj):
        """Show percentage as a coloured badge."""
        pct = obj.percentage_used
        color = "#ef4444" if pct >= 90 else "#f59e0b" if pct >= 70 else "#22c55e"
        return format_html(
            '<span style="color: {}; font-weight: 600;">{:.1f}%</span>',
            color, pct,
        )

    percentage_used_display.short_description = "% Used"

    def remaining_display(self, obj):
        """Show remaining credits."""
        return f"{obj.remaining:,}"

    remaining_display.short_description = "Remaining"
