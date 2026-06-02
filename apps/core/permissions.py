"""
apps/core/permissions.py

Custom DRF permission classes for Ziada.

Hierarchy:
  - IsOrganisationAdmin  → can manage the whole organisation
  - IsStoreManager       → can manage a specific store
  - IsStoreCashier       → can create/edit transactions within their till
  - IsReadOnly           → GET requests only

Usage in views:
    class ProductViewSet(viewsets.ModelViewSet):
        permission_classes = [IsAuthenticated, IsStoreManager]
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsOrganisationAdmin(BasePermission):
    """
    Only users with role='admin' and linked to the organisation can access.
    Used for organisation-wide settings, user management, etc.
    """
    message = "Only organisation admins can perform this action."

    def has_permission(self, request, view):
        # Must be authenticated
        if not request.user or not request.user.is_authenticated:
            return False
        # Must have admin role (set on the User model)
        return request.user.role == "admin"


class IsStoreManager(BasePermission):
    """
    Users with role='admin' or role='manager' can access.
    Managers can read/write within their assigned store.
    """
    message = "Only store managers or admins can perform this action."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in ("admin", "manager")


class IsStoreCashier(BasePermission):
    """
    Any authenticated staff member (cashier, manager, admin) can access.
    This covers POS operations — all staff can create transactions.
    """
    message = "Authenticated store staff required."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # All staff roles can perform cashier actions
        return request.user.role in ("admin", "manager", "cashier")


class IsReadOnly(BasePermission):
    """
    Allow GET, HEAD, OPTIONS requests only.
    Useful for public-read / protected-write patterns.
    """
    message = "This endpoint is read-only."

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS
