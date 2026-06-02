"""
apps/stores/api/views.py

Endpoints:
  GET    /api/v1/stores/              → list all org stores with live KPIs
  POST   /api/v1/stores/              → create a new store (admin only)
  GET    /api/v1/stores/stats/        → org-level KPI header strip
  GET    /api/v1/stores/{id}/         → full store detail (week chart + staff roster)
  PATCH  /api/v1/stores/{id}/         → update store settings (admin/manager)
  DELETE /api/v1/stores/{id}/         → deactivate store (admin only)
  GET    /api/v1/stores/{id}/staff/   → staff roster for one store
  GET    /api/v1/stores/{id}/week/    → 7-day revenue breakdown for one store
"""

import logging

from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from apps.accounts.models import Store
from apps.core.permissions import IsStoreManager
from apps.core.response import created_response, error_response, success_response

from ..services import get_org_stats, get_staff_roster, get_store_week_breakdown
from .serializers import (
    OrgStatsSerializer,
    StoreDetailSerializer,
    StoreListSerializer,
    StoreWriteSerializer,
)

logger = logging.getLogger(__name__)


class StoreViewSet(ModelViewSet):
    """
    Store management viewset.

    All endpoints scope to the requesting user's organisation.
    Admin role required for create / delete.
    Manager role required for update.
    Any authenticated staff can read.
    """

    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter, filters.OrderingFilter]
    search_fields      = ["name", "area", "address"]
    ordering_fields    = ["name", "status", "created_at"]
    ordering           = ["name"]

    # ── Queryset ──────────────────────────────────────────────────────────────

    def _get_org(self):
        """Return the organisation for the current user (via their store)."""
        user = self.request.user
        if user.store and user.store.organisation_id:
            return user.store.organisation
        return None

    def get_queryset(self):
        org = self._get_org()
        if not org:
            return Store.objects.none()
        return (
            Store.objects
            .filter(organisation=org, is_active=True)
            .select_related("organisation")
            .prefetch_related("staff")
        )

    # ── Serializer selection ──────────────────────────────────────────────────

    def get_serializer_class(self):
        if self.action in ("create", "partial_update", "update"):
            return StoreWriteSerializer
        if self.action == "retrieve":
            return StoreDetailSerializer
        return StoreListSerializer

    # ── List ──────────────────────────────────────────────────────────────────

    def list(self, request, *args, **kwargs):
        """
        GET /api/v1/stores/
        Returns all active stores in the org with live KPIs and week sparkline.
        Optional: ?status=open|closed|paused to filter by operational status.
        """
        queryset = self.filter_queryset(self.get_queryset())

        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = StoreListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StoreListSerializer(queryset, many=True)
        return success_response(data=serializer.data)

    # ── Retrieve ──────────────────────────────────────────────────────────────

    def retrieve(self, request, *args, **kwargs):
        """
        GET /api/v1/stores/{id}/
        Returns full store detail with week revenue chart and staff roster.
        """
        store = self.get_object()
        serializer = StoreDetailSerializer(store)
        return success_response(data=serializer.data)

    # ── Create ────────────────────────────────────────────────────────────────

    def create(self, request, *args, **kwargs):
        """
        POST /api/v1/stores/
        Admin only. Automatically assigns to the user's organisation.
        """
        if request.user.role != "admin":
            return error_response("Only organisation admins can create stores.", status=403)

        org = self._get_org()
        if not org:
            return error_response("User is not linked to an organisation.", status=400)

        data = request.data.copy()
        data["organisation"] = str(org.id)

        serializer = StoreWriteSerializer(data=data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        store = serializer.save()
        logger.info("Admin %s created store '%s'.", request.user.username, store.name)
        return created_response(
            data=StoreListSerializer(store).data,
            message=f"Store '{store.name}' created.",
        )

    # ── Partial update ────────────────────────────────────────────────────────

    def partial_update(self, request, *args, **kwargs):
        """
        PATCH /api/v1/stores/{id}/
        Managers can update their own store; admins can update any store.
        """
        store = self.get_object()

        if request.user.role not in ("admin", "manager"):
            return error_response("Only managers or admins can update stores.", status=403)

        # Managers can only update their own assigned store
        if request.user.role == "manager" and request.user.store_id != store.id:
            return error_response("You can only update your own store.", status=403)

        serializer = StoreWriteSerializer(store, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        serializer.save()
        logger.info("User %s updated store '%s'.", request.user.username, store.name)
        return success_response(
            data=StoreDetailSerializer(store).data,
            message="Store updated.",
        )

    # ── Destroy (deactivate) ──────────────────────────────────────────────────

    def destroy(self, request, *args, **kwargs):
        """
        DELETE /api/v1/stores/{id}/
        Admin only. Soft-deactivates: sets is_active=False and status=paused.
        """
        if request.user.role != "admin":
            return error_response("Only organisation admins can deactivate stores.", status=403)

        store = self.get_object()
        store.is_active = False
        store.status    = Store.STATUS_PAUSED
        store.save(update_fields=["is_active", "status", "updated_at"])
        logger.info("Admin %s deactivated store '%s'.", request.user.username, store.name)
        return success_response(message=f"Store '{store.name}' deactivated.")

    # ── Extra actions ─────────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """
        GET /api/v1/stores/stats/
        Org-level KPI header strip: stores open, total revenue, txns, staff on duty.
        """
        org = self._get_org()
        if not org:
            return error_response("User is not linked to an organisation.", status=400)

        data = get_org_stats(org)
        serializer = OrgStatsSerializer(data)
        return success_response(data=serializer.data)

    @action(detail=True, methods=["get"], url_path="staff")
    def staff(self, request, pk=None):
        """
        GET /api/v1/stores/{id}/staff/
        Staff roster with on-duty flag for the store detail Staff tab.
        """
        store = self.get_object()
        roster = get_staff_roster(store)
        return success_response(
            data=roster,
            meta={"count": len(roster)},
        )

    @action(detail=True, methods=["get"], url_path="week")
    def week(self, request, pk=None):
        """
        GET /api/v1/stores/{id}/week/
        7-day daily revenue breakdown for the store detail Overview chart.
        """
        store = self.get_object()
        breakdown = get_store_week_breakdown(store)
        return success_response(data=breakdown)

    @action(detail=True, methods=["patch"], url_path="status",
            permission_classes=[IsAuthenticated, IsStoreManager])
    def set_status(self, request, pk=None):
        """
        PATCH /api/v1/stores/{id}/status/
        Quick status toggle (open / closed / paused) without a full PATCH.
        Body: { "status": "open" | "closed" | "paused" }
        """
        store = self.get_object()
        new_status = request.data.get("status")

        valid = [Store.STATUS_OPEN, Store.STATUS_CLOSED, Store.STATUS_PAUSED]
        if new_status not in valid:
            return error_response(
                f"Invalid status. Must be one of: {', '.join(valid)}.",
                status=400,
            )

        store.status = new_status
        store.save(update_fields=["status", "updated_at"])
        logger.info(
            "User %s set store '%s' status to '%s'.",
            request.user.username, store.name, new_status,
        )
        return success_response(
            data={"status": store.status},
            message=f"Store status updated to '{new_status}'.",
        )
