"""
apps/suppliers/api/views.py

Endpoints:
  SupplierViewSet        → /api/v1/suppliers/
  SupplierDeliveryViewSet → /api/v1/suppliers/deliveries/
  SupplierPaymentViewSet  → /api/v1/suppliers/payments/ (read-only)

Extra actions on SupplierViewSet:
  GET  /suppliers/stats/             → KPI header strip
  GET  /suppliers/{id}/deliveries/   → deliveries for one supplier
  POST /suppliers/{id}/deliveries/   → add delivery to one supplier
  GET  /suppliers/{id}/payments/     → payments for one supplier
  POST /suppliers/{id}/pay/          → record a payment

Extra action on SupplierDeliveryViewSet:
  POST /suppliers/deliveries/{id}/pay/ → mark delivery paid
"""

import logging

from django.db import transaction as db_transaction
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.core.permissions import IsStoreManager
from apps.core.response import created_response, error_response, success_response

from ..models import Supplier, SupplierDelivery, SupplierPayment
from ..services import get_supplier_stats, mark_delivery_paid
from .serializers import (
    RecordPaymentSerializer,
    SupplierDeliverySerializer,
    SupplierPaymentSerializer,
    SupplierSerializer,
)

logger = logging.getLogger(__name__)


class SupplierViewSet(ModelViewSet):
    """
    Full CRUD for suppliers + nested delivery/payment actions.

    GET    /api/v1/suppliers/
    POST   /api/v1/suppliers/
    GET    /api/v1/suppliers/stats/
    GET    /api/v1/suppliers/{id}/
    PATCH  /api/v1/suppliers/{id}/
    DELETE /api/v1/suppliers/{id}/
    GET    /api/v1/suppliers/{id}/deliveries/
    POST   /api/v1/suppliers/{id}/deliveries/
    GET    /api/v1/suppliers/{id}/payments/
    POST   /api/v1/suppliers/{id}/pay/
    """

    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "category", "rep", "phone", "email"]
    ordering_fields = ["name", "status", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        return Supplier.objects.filter(
            store=self.request.user.store
        ).select_related("store", "organisation")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        data["store"] = str(request.user.store_id)
        data["organisation"] = str(request.user.store.organisation_id)
        serializer = SupplierSerializer(data=data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        supplier = serializer.save()
        logger.info("User %s created supplier '%s'.", request.user.username, supplier.name)
        return created_response(
            data=SupplierSerializer(supplier).data,
            message=f"Supplier '{supplier.name}' created.",
        )

    def partial_update(self, request, *args, **kwargs):
        supplier = self.get_object()
        serializer = SupplierSerializer(supplier, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        serializer.save()
        return success_response(
            data=SupplierSerializer(supplier).data,
            message="Supplier updated.",
        )

    def destroy(self, request, *args, **kwargs):
        supplier = self.get_object()
        supplier.status = "inactive"
        supplier.save(update_fields=["status", "updated_at"])
        logger.info("User %s deactivated supplier '%s'.", request.user.username, supplier.name)
        return success_response(message=f"Supplier '{supplier.name}' deactivated.")

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """GET /api/v1/suppliers/stats/ — KPI header strip."""
        data = get_supplier_stats(store=request.user.store)
        return success_response(data=data)

    @action(detail=True, methods=["get", "post"], url_path="deliveries")
    def deliveries(self, request, pk=None):
        """
        GET  → list deliveries for this supplier.
        POST → record a new delivery.
        """
        supplier = self.get_object()

        if request.method == "GET":
            qs = supplier.deliveries.select_related("recorded_by").order_by("-delivery_date")
            serializer = SupplierDeliverySerializer(qs, many=True)
            return success_response(data=serializer.data)

        data = request.data.copy()
        data["supplier"]     = str(supplier.id)
        data["store"]        = str(request.user.store_id)
        data["organisation"] = str(request.user.store.organisation_id)
        serializer = SupplierDeliverySerializer(data=data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        delivery = serializer.save(recorded_by=request.user)
        return created_response(
            data=SupplierDeliverySerializer(delivery).data,
            message="Delivery recorded.",
        )

    @action(detail=True, methods=["get"], url_path="payments")
    def payments(self, request, pk=None):
        """GET /api/v1/suppliers/{id}/payments/ — payment history."""
        supplier = self.get_object()
        qs = supplier.payments.select_related("recorded_by", "delivery").order_by("-payment_date")
        serializer = SupplierPaymentSerializer(qs, many=True)
        return success_response(data=serializer.data)

    @action(detail=True, methods=["post"], url_path="pay",
            permission_classes=[IsAuthenticated, IsStoreManager])
    def pay(self, request, pk=None):
        """
        POST /api/v1/suppliers/{id}/pay/
        Body: { amount, payment_method, reference?, delivery?, notes? }
        """
        supplier = self.get_object()
        serializer = RecordPaymentSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        vd = serializer.validated_data
        delivery = None
        if vd.get("delivery"):
            try:
                delivery = SupplierDelivery.objects.get(id=vd["delivery"], supplier=supplier)
            except SupplierDelivery.DoesNotExist:
                return error_response("Delivery not found for this supplier.")

        with db_transaction.atomic():
            if delivery:
                payment = mark_delivery_paid(
                    delivery=delivery,
                    user=request.user,
                    amount=vd["amount"],
                    method=vd["payment_method"],
                    reference=vd.get("reference", ""),
                )
            else:
                payment = SupplierPayment.objects.create(
                    supplier=supplier,
                    store=request.user.store,
                    organisation=request.user.store.organisation,
                    amount=vd["amount"],
                    payment_date=timezone.now().date(),
                    payment_method=vd["payment_method"],
                    reference=vd.get("reference", ""),
                    notes=vd.get("notes", ""),
                    recorded_by=request.user,
                )

        logger.info(
            "User %s recorded payment of TZS %s to supplier '%s'.",
            request.user.username, vd["amount"], supplier.name,
        )
        return created_response(
            data=SupplierPaymentSerializer(payment).data,
            message=f"Payment of TZS {vd['amount']:,} recorded.",
        )


class SupplierDeliveryViewSet(ModelViewSet):
    """
    CRUD for deliveries across all suppliers.

    GET    /api/v1/suppliers/deliveries/
    POST   /api/v1/suppliers/deliveries/
    GET    /api/v1/suppliers/deliveries/{id}/
    PATCH  /api/v1/suppliers/deliveries/{id}/
    DELETE /api/v1/suppliers/deliveries/{id}/
    POST   /api/v1/suppliers/deliveries/{id}/pay/

    Query params:
      ?unpaid=true       → filter to unpaid invoices only
      ?supplier=<uuid>   → filter by supplier
    """

    serializer_class = SupplierDeliverySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["invoice_number", "supplier__name"]
    ordering_fields = ["delivery_date", "total_value", "created_at"]
    ordering = ["-delivery_date"]

    def get_queryset(self):
        return SupplierDelivery.objects.filter(
            store=self.request.user.store
        ).select_related("supplier", "recorded_by")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        if request.query_params.get("unpaid") == "true":
            queryset = queryset.filter(is_paid=False)
        supplier_id = request.query_params.get("supplier")
        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        data["store"]        = str(request.user.store_id)
        data["organisation"] = str(request.user.store.organisation_id)
        serializer = SupplierDeliverySerializer(data=data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        delivery = serializer.save(recorded_by=request.user)
        return created_response(
            data=SupplierDeliverySerializer(delivery).data,
            message="Delivery recorded.",
        )

    def partial_update(self, request, *args, **kwargs):
        delivery = self.get_object()
        serializer = SupplierDeliverySerializer(delivery, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        serializer.save()
        return success_response(
            data=SupplierDeliverySerializer(delivery).data,
            message="Delivery updated.",
        )

    def destroy(self, request, *args, **kwargs):
        delivery = self.get_object()
        delivery.delete()
        return success_response(message="Delivery deleted.")

    @action(detail=True, methods=["post"], url_path="pay",
            permission_classes=[IsAuthenticated, IsStoreManager])
    def pay(self, request, pk=None):
        """
        POST /api/v1/suppliers/deliveries/{id}/pay/
        Mark this delivery paid and record the payment.
        """
        delivery = self.get_object()
        serializer = RecordPaymentSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        vd = serializer.validated_data
        payment = mark_delivery_paid(
            delivery=delivery,
            user=request.user,
            amount=vd["amount"],
            method=vd["payment_method"],
            reference=vd.get("reference", ""),
        )
        return created_response(
            data=SupplierPaymentSerializer(payment).data,
            message=f"Payment of TZS {vd['amount']:,} recorded.",
        )


class SupplierPaymentViewSet(ReadOnlyModelViewSet):
    """
    Read-only listing of all payments for this store.

    GET /api/v1/suppliers/payments/
    GET /api/v1/suppliers/payments/{id}/

    Query params:
      ?supplier=<uuid>  → filter by supplier
    """

    serializer_class = SupplierPaymentSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["payment_date", "amount", "created_at"]
    ordering = ["-payment_date"]

    def get_queryset(self):
        return SupplierPayment.objects.filter(
            store=self.request.user.store
        ).select_related("supplier", "delivery", "recorded_by")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        supplier_id = request.query_params.get("supplier")
        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)
