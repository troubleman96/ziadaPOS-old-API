"""
apps/staff/api/views.py

Staff management API — a clean, dedicated surface for the /staff UI pages.

All endpoints are store-scoped: a manager sees only their store's staff;
an admin can supply ?store=<id> to view another store.

Endpoints
─────────
GET    /api/v1/staff/                     list (filters: ?role= ?status= ?search= ?shift=)
POST   /api/v1/staff/                     create staff member
GET    /api/v1/staff/kpis/                store-level KPIs (count, on-shift, sales today)
GET    /api/v1/staff/{id}/                detail with full stats
PATCH  /api/v1/staff/{id}/               update profile fields
DELETE /api/v1/staff/{id}/               deactivate (soft delete)
GET    /api/v1/staff/{id}/stats/          performance stats only
PATCH  /api/v1/staff/{id}/shift/          update shift + employment_status
PATCH  /api/v1/staff/{id}/permissions/   update can_refund / can_discount / can_view_reports
GET    /api/v1/staff/{id}/activity/       today's transaction activity feed
"""

import logging

from django.db.models import Q
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ViewSet

from apps.accounts.models import User
from apps.core.permissions import IsStoreManager
from apps.core.response import created_response, error_response, success_response

from ..services import (
    annotate_queryset_with_stats,
    get_staff_activity,
    get_staff_stats,
    get_store_kpis,
)
from .serializers import (
    PermissionsUpdateSerializer,
    ShiftUpdateSerializer,
    StaffActivityEntrySerializer,
    StaffCreateSerializer,
    StaffKPISerializer,
    StaffSerializer,
    StaffStatsSerializer,
    StaffUpdateSerializer,
)

logger = logging.getLogger(__name__)


def _base_qs(request):
    """
    Return the base User queryset scoped to the requesting user's store.
    Admins can override with ?store=<id>.
    """
    qs = User.objects.select_related("store", "store__organisation")

    if request.user.role == User.ROLE_ADMIN:
        store_id = request.query_params.get("store") or (
            request.user.store_id if request.user.store_id else None
        )
        if store_id:
            qs = qs.filter(store_id=store_id)
    else:
        if request.user.store_id:
            qs = qs.filter(store=request.user.store)
        else:
            qs = qs.none()

    return qs


class StaffViewSet(ViewSet):
    """
    ViewSet for staff management.
    Uses a plain ViewSet (not ModelViewSet) so every action is explicit
    and maps cleanly to the UI's data needs.
    """

    permission_classes = [IsAuthenticated, IsStoreManager]

    # ── List ─────────────────────────────────────────────────────────────────

    def list(self, request):
        """
        GET /api/v1/staff/
        Returns all staff for the user's store with performance stats.

        Query params:
          ?role=admin|manager|cashier
          ?status=active|on_leave|inactive   (employment_status)
          ?shift=morning|evening|full_day|weekend
          ?search=<name or phone or email>
          ?ordering=name|-name|joined|-joined|sales_today|-sales_today
        """
        qs = _base_qs(request)

        # ── Filters ──────────────────────────────────────────────────────────
        role = request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)

        status = request.query_params.get("status")
        if status:
            qs = qs.filter(employment_status=status)

        shift = request.query_params.get("shift")
        if shift:
            qs = qs.filter(shift=shift)

        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)  |
                Q(phone__icontains=search)       |
                Q(email__icontains=search)
            )

        # ── Annotate with transaction stats (single JOIN) ────────────────────
        qs = annotate_queryset_with_stats(qs)

        # ── Ordering ────────────────────────────────────────────────────────
        ordering = request.query_params.get("ordering", "first_name")
        safe_orderings = {
            "name":        ["first_name", "last_name"],
            "-name":       ["-first_name", "-last_name"],
            "joined":      ["date_joined"],
            "-joined":     ["-date_joined"],
            "role":        ["role"],
            "sales_today": ["_sales_today"],
            "-sales_today": ["-_sales_today"],
        }
        qs = qs.order_by(*safe_orderings.get(ordering, ["first_name", "last_name"]))

        serializer = StaffSerializer(qs, many=True)
        return success_response(data=serializer.data)

    # ── KPIs (must be before {id} routes so router matches it first) ──────────

    @action(detail=False, methods=["get"], url_path="kpis")
    def kpis(self, request):
        """
        GET /api/v1/staff/kpis/
        Store-level staff KPIs: total, active, on-shift today, sales today.
        """
        store = request.user.store
        if not store:
            return error_response("User is not assigned to a store.", status=400)

        data = get_store_kpis(store)
        return success_response(data=StaffKPISerializer(data).data)

    # ── Create ────────────────────────────────────────────────────────────────

    def create(self, request):
        """
        POST /api/v1/staff/
        Create a new staff member scoped to the requesting user's store.
        """
        store = request.user.store
        if not store:
            return error_response("You must be assigned to a store to add staff.", status=400)

        # username defaults to phone number if not provided
        data = request.data.copy()
        if not data.get("username") and data.get("phone"):
            data["username"] = data["phone"].replace(" ", "").replace("+", "")

        serializer = StaffCreateSerializer(data=data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        member = serializer.save(store=store, organisation=store.organisation)
        logger.info(
            "User %s created staff member '%s' (role=%s).",
            request.user.username, member.full_name, member.role,
        )
        return created_response(
            data=StaffSerializer(member).data,
            message=f"'{member.full_name}' added to the team.",
        )

    # ── Retrieve ──────────────────────────────────────────────────────────────

    def retrieve(self, request, pk=None):
        """
        GET /api/v1/staff/{id}/
        Returns the full staff member profile including computed performance stats.
        """
        try:
            member = _base_qs(request).get(pk=pk)
        except User.DoesNotExist:
            return error_response("Staff member not found.", status=404)

        # Compute stats via services (no annotation needed for single object)
        stats = get_staff_stats(member)

        # Attach stats as attributes so StaffSerializer can pick them up
        member._sales_today  = stats["sales_today"]
        member._txns_today   = stats["txns_today"]
        member._total_sales  = stats["total_sales"]
        member._avg_ticket   = stats["avg_ticket"]
        member._txns_total   = stats["txns_total"]

        serializer = StaffSerializer(member)
        return success_response(data=serializer.data)

    # ── Update ────────────────────────────────────────────────────────────────

    def partial_update(self, request, pk=None):
        """
        PATCH /api/v1/staff/{id}/
        Update any combination of profile, shift, or permission fields.
        """
        try:
            member = _base_qs(request).get(pk=pk)
        except User.DoesNotExist:
            return error_response("Staff member not found.", status=404)

        serializer = StaffUpdateSerializer(member, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        serializer.save()
        logger.info("User %s updated staff member %s.", request.user.username, member.pk)
        return success_response(
            data=StaffSerializer(member).data,
            message="Staff member updated.",
        )

    # ── Deactivate (soft delete) ───────────────────────────────────────────────

    def destroy(self, request, pk=None):
        """
        DELETE /api/v1/staff/{id}/
        Soft-deactivates: sets employment_status=inactive and is_active=False.
        Does not delete the record — preserves transaction history.
        Cannot deactivate yourself.
        """
        try:
            member = _base_qs(request).get(pk=pk)
        except User.DoesNotExist:
            return error_response("Staff member not found.", status=404)

        if member.pk == request.user.pk:
            return error_response("You cannot deactivate your own account.", status=400)

        member.employment_status = User.EMPLOYMENT_INACTIVE
        member.is_active = False
        member.save(update_fields=["employment_status", "is_active", "updated_at"])
        logger.info(
            "User %s deactivated staff member '%s'.",
            request.user.username, member.full_name,
        )
        return success_response(message=f"'{member.full_name}' has been deactivated.")

    # ── Stats action ──────────────────────────────────────────────────────────

    @action(detail=True, methods=["get"], url_path="stats")
    def stats(self, request, pk=None):
        """
        GET /api/v1/staff/{id}/stats/
        Returns detailed performance stats for a single staff member.
        """
        try:
            member = _base_qs(request).get(pk=pk)
        except User.DoesNotExist:
            return error_response("Staff member not found.", status=404)

        data = get_staff_stats(member)
        return success_response(data=StaffStatsSerializer(data).data)

    # ── Shift action ──────────────────────────────────────────────────────────

    @action(detail=True, methods=["patch"], url_path="shift")
    def shift(self, request, pk=None):
        """
        PATCH /api/v1/staff/{id}/shift/
        Body: { shift?, employment_status? }
        Updates shift assignment and/or employment status independently
        of the main profile PATCH.
        """
        try:
            member = _base_qs(request).get(pk=pk)
        except User.DoesNotExist:
            return error_response("Staff member not found.", status=404)

        serializer = ShiftUpdateSerializer(member, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        serializer.save()
        logger.info(
            "User %s updated shift for '%s': shift=%s status=%s.",
            request.user.username, member.full_name,
            member.shift, member.employment_status,
        )
        return success_response(
            data={
                "shift":             member.shift,
                "employment_status": member.employment_status,
            },
            message="Shift updated.",
        )

    # ── Permissions action ────────────────────────────────────────────────────

    @action(detail=True, methods=["patch"], url_path="permissions")
    def permissions(self, request, pk=None):
        """
        PATCH /api/v1/staff/{id}/permissions/
        Body: { can_refund?, can_discount?, can_view_reports? }
        Updates POS permission flags for this staff member.
        Only managers and admins can change permissions.
        """
        try:
            member = _base_qs(request).get(pk=pk)
        except User.DoesNotExist:
            return error_response("Staff member not found.", status=404)

        # Owners cannot have their permissions stripped by a manager
        if member.role == User.ROLE_ADMIN and request.user.role == User.ROLE_MANAGER:
            return error_response(
                "Managers cannot modify Owner permissions.", status=403
            )

        serializer = PermissionsUpdateSerializer(member, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        serializer.save()
        logger.info(
            "User %s updated permissions for '%s'.",
            request.user.username, member.full_name,
        )
        return success_response(
            data={
                "can_refund":       member.can_refund,
                "can_discount":     member.can_discount,
                "can_view_reports": member.can_view_reports,
            },
            message="Permissions updated.",
        )

    # ── Activity action ───────────────────────────────────────────────────────

    @action(detail=True, methods=["get"], url_path="activity")
    def activity(self, request, pk=None):
        """
        GET /api/v1/staff/{id}/activity/
        Returns today's transaction activity feed for this staff member.
        Optional: ?date=2026-05-25 for a specific date (YYYY-MM-DD).
        """
        try:
            member = _base_qs(request).get(pk=pk)
        except User.DoesNotExist:
            return error_response("Staff member not found.", status=404)

        date_str = request.query_params.get("date")
        date = None
        if date_str:
            from datetime import date as _date
            try:
                date = _date.fromisoformat(date_str)
            except ValueError:
                return error_response("Invalid date format. Use YYYY-MM-DD.", status=400)

        entries = get_staff_activity(member, date=date)
        return success_response(
            data=StaffActivityEntrySerializer(entries, many=True).data,
        )
