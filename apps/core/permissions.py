"""
apps/core/permissions.py

Custom DRF permission classes for Ziada POS.

Role hierarchy:
  admin  → Cameltech platform admin. Access to everything.
  owner  → Business owner. Full access within their own organisation.
  staff  → Store employee. POS access within their assigned store.

Permission class map:
  IsSystemAdmin   → role == "admin"                    (Cameltech only)
  IsOwner         → role in ("admin", "owner")         (org-level management)
  IsStoreStaff    → any authenticated role             (POS operations)
  IsReadOnly      → SAFE_METHODS only

Backward-compatible aliases (for existing views not yet migrated):
  IsOrganisationAdmin → IsSystemAdmin
  IsStoreManager      → IsOwner
  IsStoreCashier      → IsStoreStaff
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsSystemAdmin(BasePermission):
    """
    Cameltech platform admin only (role='admin').
    Used for: subscription plan management, platform-wide admin panel.
    """
    message = "Only Cameltech system admins can perform this action."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == "admin"
        )


class IsOwner(BasePermission):
    """
    Business owners and system admins (role in 'admin', 'owner').
    Used for: org settings, store creation, staff management, reports.
    """
    message = "Only store owners or system admins can perform this action."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ("admin", "owner")
        )


class IsStoreStaff(BasePermission):
    """
    Any authenticated user with a valid role (admin, owner, staff).
    Used for: POS operations, transactions, credit tabs.
    """
    message = "Authenticated store staff required."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ("admin", "owner", "staff")
        )


class IsReadOnly(BasePermission):
    """Allow GET, HEAD, OPTIONS only."""
    message = "This endpoint is read-only."

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS


# ── Backward-compatible aliases ────────────────────────────────────────────────
# Existing views reference these names; aliased so they don't break while we
# migrate view-by-view to the new names.

IsOrganisationAdmin = IsSystemAdmin   # old name → now Cameltech-admin only
IsStoreManager      = IsOwner         # old name → now owner + admin
IsStoreCashier      = IsStoreStaff    # old name → now all staff roles
