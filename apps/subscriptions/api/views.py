"""
apps/subscriptions/api/views.py

Subscription API views.

Access rules:
  - GET  /plans/              → anyone (AllowAny — shown on registration page)
  - POST /plans/              → admin only (Cameltech creates plans)
  - PATCH/DELETE /plans/{id}/ → admin only
  - GET  /my-subscription/    → owner (their own organisation's subscription)
  - GET  /subscriptions/      → admin only (all subscriptions)
  - POST /subscriptions/{id}/activate/ → admin only
  - PATCH /subscriptions/{id}/extra-stores/ → admin only
"""

import logging

from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.core.permissions import IsOwner, IsSystemAdmin
from apps.core.response import created_response, error_response, success_response

from ..models import Subscription, SubscriptionPlan
from .serializers import (
    ExtraStoreSerializer,
    SubscriptionActivateSerializer,
    SubscriptionPlanSerializer,
    SubscriptionSerializer,
)

logger = logging.getLogger(__name__)


class SubscriptionPlanViewSet(ModelViewSet):
    """
    GET    /api/v1/subscriptions/plans/       → list active plans (public)
    POST   /api/v1/subscriptions/plans/       → create plan (admin only)
    GET    /api/v1/subscriptions/plans/{id}/  → plan detail (public)
    PATCH  /api/v1/subscriptions/plans/{id}/  → update plan (admin only)
    DELETE /api/v1/subscriptions/plans/{id}/  → deactivate plan (admin only)
    """

    queryset         = SubscriptionPlan.objects.all()
    serializer_class = SubscriptionPlanSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return [IsAuthenticated(), IsSystemAdmin()]

    def get_queryset(self):
        qs = super().get_queryset()
        # Public listing only shows active plans
        if not (self.request.user.is_authenticated and
                getattr(self.request.user, "role", None) == "admin"):
            qs = qs.filter(is_active=True)
        return qs.order_by("sort_order", "price_per_month")

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        return success_response(
            data=SubscriptionPlanSerializer(qs, many=True).data,
            message=f"{qs.count()} plan(s) available.",
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        plan = serializer.save()
        logger.info("Admin %s created plan '%s'.", request.user.phone, plan.name)
        return created_response(
            data=SubscriptionPlanSerializer(plan).data,
            message=f"Plan '{plan.name}' created.",
        )

    def partial_update(self, request, *args, **kwargs):
        plan = self.get_object()
        serializer = self.get_serializer(plan, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        serializer.save()
        return success_response(
            data=SubscriptionPlanSerializer(plan).data,
            message="Plan updated.",
        )

    def destroy(self, request, *args, **kwargs):
        plan = self.get_object()
        plan.is_active = False
        plan.save(update_fields=["is_active", "updated_at"])
        return success_response(message=f"Plan '{plan.name}' deactivated.")


class MySubscriptionView(APIView):
    """
    GET /api/v1/subscriptions/my-subscription/
    Returns the current (latest active or most recent) subscription for the
    logged-in owner's organisation.
    """

    permission_classes = [IsAuthenticated, IsOwner]

    def get(self, request):
        org = request.user.get_organisation
        if not org:
            return error_response("No organisation linked to this account.", status=400)

        sub = (
            Subscription.objects
            .filter(organisation=org)
            .order_by("-created_at")
            .first()
        )
        if not sub:
            return error_response("No subscription found.", status=404)

        return success_response(
            data=SubscriptionSerializer(sub).data,
            message="Subscription retrieved.",
        )


class SubscriptionViewSet(ReadOnlyModelViewSet):
    """
    Admin-only full subscription list and detail.
    GET /api/v1/subscriptions/all/
    GET /api/v1/subscriptions/all/{id}/
    POST /api/v1/subscriptions/all/{id}/activate/
    PATCH /api/v1/subscriptions/all/{id}/extra-stores/
    """

    queryset         = Subscription.objects.select_related("organisation", "plan", "activated_by")
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticated, IsSystemAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        org_id = self.request.query_params.get("organisation")
        if org_id:
            qs = qs.filter(organisation_id=org_id)
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        return success_response(
            data=SubscriptionSerializer(qs, many=True).data,
            message=f"{qs.count()} subscription(s).",
        )

    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        """
        POST /api/v1/subscriptions/all/{id}/activate/
        Cameltech admin confirms payment and activates the subscription.
        """
        sub = self.get_object()
        serializer = SubscriptionActivateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        data = serializer.validated_data
        sub.status             = data["status"]
        sub.activated_by       = request.user
        sub.payment_reference  = data.get("payment_reference", sub.payment_reference)
        sub.payment_date       = data.get("payment_date", sub.payment_date) or timezone.now().date()
        sub.amount_paid        = data.get("amount_paid", sub.amount_paid)
        sub.notes              = data.get("notes", sub.notes)
        sub.save()

        # Sync organisation plan field
        if data["status"] == Subscription.STATUS_ACTIVE:
            org = sub.organisation
            org.plan = "pro"
            org.save(update_fields=["plan", "updated_at"])

        logger.info("Admin %s activated subscription %s for org '%s'.",
                    request.user.phone, sub.id, sub.organisation.name)
        return success_response(
            data=SubscriptionSerializer(sub).data,
            message="Subscription activated.",
        )

    @action(detail=True, methods=["patch"], url_path="extra-stores")
    def extra_stores(self, request, pk=None):
        """
        PATCH /api/v1/subscriptions/all/{id}/extra-stores/
        Add or update the number of extra paid stores for this subscription.
        """
        sub = self.get_object()
        serializer = ExtraStoreSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        sub.extra_stores = serializer.validated_data["extra_stores"]
        sub.save(update_fields=["extra_stores", "updated_at"])

        # Update organisation max_stores
        org = sub.organisation
        org.max_stores = sub.max_stores_allowed
        org.save(update_fields=["max_stores", "updated_at"])

        return success_response(
            data=SubscriptionSerializer(sub).data,
            message=f"Extra stores updated to {sub.extra_stores}.",
        )
