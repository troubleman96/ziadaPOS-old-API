"""
apps/suppliers/api/serializers.py

Serializers for the suppliers app:
  SupplierSerializer         — full supplier record with computed KPIs
  SupplierMinimalSerializer  — id/name/phone/status for embedding
  SupplierDeliverySerializer — delivery (invoice) record
  SupplierPaymentSerializer  — payment ledger entry
  RecordPaymentSerializer    — input for POST .../pay/ actions
"""

from rest_framework import serializers

from ..models import (
    PAYMENT_METHOD_CHOICES,
    METHOD_CASH,
    Supplier,
    SupplierDelivery,
    SupplierPayment,
)


class SupplierSerializer(serializers.ModelSerializer):
    outstanding_balance    = serializers.IntegerField(read_only=True)
    pending_invoices_count = serializers.IntegerField(read_only=True)
    last_delivery_date     = serializers.DateField(read_only=True)
    product_count          = serializers.IntegerField(read_only=True)

    class Meta:
        model = Supplier
        fields = [
            "id", "store", "organisation",
            "name", "category", "rep", "phone", "email", "address",
            "payment_terms", "status", "notes",
            "outstanding_balance", "pending_invoices_count",
            "last_delivery_date", "product_count",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class SupplierMinimalSerializer(serializers.ModelSerializer):
    """Lean representation for embedding in other responses."""

    class Meta:
        model = Supplier
        fields = ["id", "name", "phone", "status"]


class SupplierDeliverySerializer(serializers.ModelSerializer):
    supplier_name    = serializers.CharField(source="supplier.name", read_only=True)
    recorded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SupplierDelivery
        fields = [
            "id", "supplier", "supplier_name", "store", "organisation",
            "invoice_number", "delivery_date", "items_count", "total_value",
            "status", "is_paid",
            "recorded_by", "recorded_by_name", "notes",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_recorded_by_name(self, obj):
        if obj.recorded_by:
            return obj.recorded_by.get_full_name() or obj.recorded_by.username
        return None


class SupplierPaymentSerializer(serializers.ModelSerializer):
    supplier_name    = serializers.CharField(source="supplier.name", read_only=True)
    recorded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SupplierPayment
        fields = [
            "id", "supplier", "supplier_name", "store", "organisation",
            "delivery",
            "amount", "payment_date", "payment_method", "reference",
            "recorded_by", "recorded_by_name", "notes",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_recorded_by_name(self, obj):
        if obj.recorded_by:
            return obj.recorded_by.get_full_name() or obj.recorded_by.username
        return None


class RecordPaymentSerializer(serializers.Serializer):
    """Input body for POST .../pay/ endpoints."""

    amount         = serializers.IntegerField(min_value=1)
    payment_method = serializers.ChoiceField(choices=PAYMENT_METHOD_CHOICES, default=METHOD_CASH)
    reference      = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    delivery       = serializers.UUIDField(required=False, allow_null=True, default=None)
    notes          = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
