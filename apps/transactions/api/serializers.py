"""
apps/transactions/api/serializers.py

Serializers for Transaction and TransactionLine.

The key challenge here is the POS "complete sale" serializer:
  - Input: list of cart items + payment method + discount + customer
  - Processing: calculate all monetary fields, deduct stock
  - Output: full transaction with line items

Referenced from the UI CartPanel in /pos page:
  lines: [{ product.id, product.name, product.sku, product.price, qty }]
  payment: "Cash" | "M-Pesa" | "Tigo Pesa" | "Bank" | "Credit"
  discount: 0–50 (percentage)
  customer: optional customer id or walk-in name
"""

from django.conf import settings
from rest_framework import serializers

from ..models import Transaction, TransactionLine


# ── Transaction Line ──────────────────────────────────────────────────────────

class TransactionLineSerializer(serializers.ModelSerializer):
    """
    Read serialiser for transaction line items.
    Used in transaction detail view — shows each product sold.
    """

    # Computed from model properties
    line_total  = serializers.IntegerField(read_only=True)
    line_cost   = serializers.IntegerField(read_only=True)
    line_profit = serializers.IntegerField(read_only=True)

    class Meta:
        model = TransactionLine
        fields = [
            "id",
            "product", "product_name", "product_sku",
            "unit_price", "unit_cost", "qty",
            "line_total", "line_cost", "line_profit",
        ]
        read_only_fields = ["id", "line_total", "line_cost", "line_profit"]


# ── Transaction (read) ────────────────────────────────────────────────────────

class TransactionSerializer(serializers.ModelSerializer):
    """
    Read serialiser for transactions — used in list and detail views.
    Includes nested line items and computed display fields.
    """

    # Nested line items (all lines for this transaction)
    lines = TransactionLineSerializer(many=True, read_only=True)

    # Cashier display name
    cashier_name = serializers.SerializerMethodField()

    # Computed counts
    item_count = serializers.IntegerField(read_only=True)
    sku_count  = serializers.IntegerField(read_only=True)

    class Meta:
        model = Transaction
        fields = [
            # Reference
            "id", "txn_number", "store", "channel",

            # Customer
            "customer", "customer_name", "customer_phone",

            # Payment
            "payment_method", "payment_reference", "status",

            # Amounts
            "subtotal", "discount_pct", "discount_amount",
            "tax_amount", "total", "cost_total", "profit",

            # Staff
            "cashier", "cashier_name", "till_number",

            # Computed
            "item_count", "sku_count",

            # Lines
            "lines",

            # Meta
            "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "txn_number", "created_at", "updated_at"]

    def get_cashier_name(self, obj):
        """Return cashier's full name or username."""
        if obj.cashier:
            return obj.cashier.get_full_name() or obj.cashier.username
        return "Unknown"


class TransactionListSerializer(serializers.ModelSerializer):
    """
    Lightweight serialiser for transaction LIST view — no nested lines.
    Keeps the list response lean for the /transactions page table.
    """

    cashier_name = serializers.SerializerMethodField()
    sku_count    = serializers.IntegerField(read_only=True)
    item_count   = serializers.IntegerField(read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id", "txn_number", "store",
            "customer_name", "customer_phone",
            "payment_method", "payment_reference", "status",
            "subtotal", "discount_pct", "discount_amount",
            "total", "profit",
            "cashier_name", "till_number",
            "sku_count", "item_count",
            "created_at",
        ]

    def get_cashier_name(self, obj):
        if obj.cashier:
            return obj.cashier.get_full_name() or obj.cashier.username
        return "Unknown"


# ── Cart item input ───────────────────────────────────────────────────────────

class CartItemSerializer(serializers.Serializer):
    """
    One item in the POS cart.
    The frontend sends this when completing a sale.

    Matches the CartItem type from /pos page:
      { product: Product, qty: number }
    """

    # Product UUID
    product_id = serializers.UUIDField(
        help_text="UUID of the product being sold.",
    )

    # Quantity in cart
    qty = serializers.IntegerField(
        min_value=1,
        help_text="Number of units to sell (must be >= 1).",
    )


# ── Complete Sale (POS checkout) ──────────────────────────────────────────────

class CompleteSaleSerializer(serializers.Serializer):
    """
    Input serialiser for the POST /transactions/complete-sale/ endpoint.

    The POS sends this payload when the cashier clicks "Complete sale":
      {
        "items":            [{ "product_id": "...", "qty": 2 }, ...],
        "payment_method":   "M-Pesa",
        "payment_reference":"QGT5K3AB",    (optional — M-Pesa code)
        "discount_pct":     5,             (optional — 0 by default)
        "till_number":      "Till #2",
        "customer_id":      "...",         (optional — walk-in if null)
        "notes":            ""             (optional)
      }
    """

    # Cart items — must have at least one
    items = CartItemSerializer(
        many=True,
        help_text="List of products and quantities in the cart.",
    )

    # Payment method — validated against allowed choices
    payment_method = serializers.ChoiceField(
        choices=Transaction.METHOD_CHOICES,
        default=Transaction.METHOD_CASH,
    )

    # Optional mobile money or bank reference
    payment_reference = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )

    # Discount percentage (0–50) — same as POS UI discount stepper
    discount_pct = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=0,
        max_value=50,
        default=0,
    )

    # Which register/till is being used
    till_number = serializers.CharField(
        max_length=20,
        default="Till #1",
    )

    # Optional registered customer ID (null = walk-in)
    customer_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Customer UUID (leave null for walk-in customers).",
    )

    # Optional notes (refund reason, etc.)
    notes = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        default="",
    )

    def validate_items(self, items):
        """Must have at least one item in the cart."""
        if not items:
            raise serializers.ValidationError("Cart must contain at least one item.")
        return items

    def validate(self, attrs):
        """Credit sales require a registered customer — a walk-in has nobody to bill."""
        if (
            attrs.get("payment_method") == "Credit"
            and not attrs.get("customer_id")
        ):
            raise serializers.ValidationError(
                {"customer_id": "A registered customer must be selected for credit sales."}
            )
        return attrs


# ── Refund ────────────────────────────────────────────────────────────────────

class RefundSerializer(serializers.Serializer):
    """
    Input serialiser for POST /transactions/{id}/refund/
    Marks a transaction as refunded and restores stock.
    """

    reason = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default="",
        help_text="Reason for the refund (optional but recommended).",
    )
