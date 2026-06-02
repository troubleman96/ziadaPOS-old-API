"""
apps/suppliers/models.py

Three models:
  Supplier         — vendor/company record with contact, terms, and status
  SupplierDelivery — each stock delivery (invoice) received from a supplier
  SupplierPayment  — each payment made to settle a supplier invoice

Design notes:
  - All monetary values in TZS integers (no sub-units).
  - Outstanding balance is computed: sum(deliveries.total_value) - sum(payments.amount).
    Not stored as a field — always derived from the ledger so it stays consistent.
  - Both SupplierDelivery and SupplierPayment are store-scoped.
  - Supplier.status replaces the simple is_active boolean from the old inventory.Supplier,
    adding the "On hold" state the UI requires.
  - inventory.Product still holds a FK to Supplier (via string ref 'suppliers.Supplier')
    so product→supplier lookups work without any cross-app circular import.
"""

from django.conf import settings
from django.db import models
from django.db.models import Sum

from apps.accounts.models import Organisation, Store
from apps.core.models import BaseModel


# ── Status / terms constants ──────────────────────────────────────────────────

STATUS_ACTIVE   = "active"
STATUS_INACTIVE = "inactive"
STATUS_ON_HOLD  = "on_hold"

STATUS_CHOICES = [
    (STATUS_ACTIVE,   "Active"),
    (STATUS_INACTIVE, "Inactive"),
    (STATUS_ON_HOLD,  "On hold"),
]

TERMS_30 = 30
TERMS_60 = 60
TERMS_90 = 90

PAYMENT_TERMS_CHOICES = [
    (TERMS_30, "30 days"),
    (TERMS_60, "60 days"),
    (TERMS_90, "90 days"),
]

# Delivery status
DELIVERY_DELIVERED = "delivered"
DELIVERY_PENDING   = "pending"
DELIVERY_PARTIAL   = "partial"

DELIVERY_STATUS_CHOICES = [
    (DELIVERY_DELIVERED, "Delivered"),
    (DELIVERY_PENDING,   "Pending"),
    (DELIVERY_PARTIAL,   "Partial"),
]

# Payment method
METHOD_CASH   = "cash"
METHOD_BANK   = "bank"
METHOD_MOBILE = "mobile"

PAYMENT_METHOD_CHOICES = [
    (METHOD_CASH,   "Cash"),
    (METHOD_BANK,   "Bank transfer"),
    (METHOD_MOBILE, "Mobile money"),
]


# ── Supplier ──────────────────────────────────────────────────────────────────

class Supplier(BaseModel):
    """
    A vendor / supplier company.

    Moved here from apps.inventory where it was a thin lookup table.
    Extended with: store scoping, rep, payment_terms, status, category.

    inventory.Product still has supplier = FK('suppliers.Supplier') so
    product-level supplier lookups continue to work.
    """

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="suppliers",
        help_text="Store this supplier record belongs to.",
    )
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="suppliers",
        help_text="Organisation (for multi-store queries).",
    )

    # ── Identity ───────────────────────────────────────────────────────────────
    name = models.CharField(
        max_length=200,
        help_text="Company / vendor name, e.g. 'Bakhresa Co.'",
    )
    category = models.CharField(
        max_length=100,
        blank=True,
        help_text="Category of goods supplied, e.g. 'Flour / Grains'.",
    )

    # ── Contact ────────────────────────────────────────────────────────────────
    rep = models.CharField(
        max_length=200,
        blank=True,
        help_text="Sales representative name, e.g. 'Joseph Mwangi'.",
    )
    phone = models.CharField(
        max_length=50,
        blank=True,
        help_text="Primary contact phone (used for WhatsApp quick-dial).",
    )
    email = models.EmailField(
        blank=True,
        help_text="Email for purchase orders.",
    )
    address = models.TextField(
        blank=True,
        help_text="Physical or postal address.",
    )

    # ── Commercial terms ───────────────────────────────────────────────────────
    payment_terms = models.PositiveSmallIntegerField(
        choices=PAYMENT_TERMS_CHOICES,
        default=TERMS_30,
        help_text="Standard payment terms in days: 30, 60, or 90.",
    )

    # ── Status ─────────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        help_text="Active = delivering regularly; On hold = paused; Inactive = no longer used.",
    )

    notes = models.TextField(
        blank=True,
        help_text="Internal notes — lead times, quality issues, negotiated rates.",
    )

    def __str__(self):
        return self.name

    # ── Computed ───────────────────────────────────────────────────────────────

    @property
    def is_active(self):
        """Convenience bool — True only when status is active."""
        return self.status == STATUS_ACTIVE

    @property
    def outstanding_balance(self):
        """
        Amount currently owed to this supplier (TZS).
        = sum of all delivery values - sum of all payments made.
        Always >= 0.
        """
        invoiced = self.deliveries.aggregate(t=Sum("total_value"))["t"] or 0
        paid     = self.payments.aggregate(t=Sum("amount"))["t"] or 0
        return max(0, invoiced - paid)

    @property
    def pending_invoices_count(self):
        """Number of deliveries that have not been fully paid."""
        return self.deliveries.filter(is_paid=False).count()

    @property
    def last_delivery_date(self):
        """Date of the most recent delivery, or None."""
        latest = self.deliveries.order_by("-delivery_date").first()
        return latest.delivery_date if latest else None

    @property
    def product_count(self):
        """Number of active products linked to this supplier."""
        return self.products.filter(is_active=True).count()

    class Meta:
        verbose_name = "Supplier"
        verbose_name_plural = "Suppliers"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["store", "status"]),
        ]


# ── SupplierDelivery ──────────────────────────────────────────────────────────

class SupplierDelivery(BaseModel):
    """
    A single stock delivery (invoice) received from a supplier.

    Each delivery represents an invoice: the supplier brings goods,
    issues an invoice, and the store owes that amount until paid.

    When is_paid is toggled to True, a SupplierPayment record should
    also exist (created by the 'Record payment' flow). The two are
    kept separate so partial payments are supported.
    """

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name="deliveries",
        help_text="Supplier who made this delivery.",
    )
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="supplier_deliveries",
        help_text="Store the delivery was made to.",
    )
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="supplier_deliveries",
    )

    # ── Invoice details ────────────────────────────────────────────────────────
    invoice_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Supplier's invoice number, e.g. 'INV-BAK-202601'.",
    )
    delivery_date = models.DateField(
        help_text="Date the goods were physically received.",
    )
    items_count = models.PositiveIntegerField(
        default=1,
        help_text="Number of line items / product types in this delivery.",
    )
    total_value = models.PositiveIntegerField(
        help_text="Total invoice value in TZS.",
    )

    # ── Status ─────────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=DELIVERY_STATUS_CHOICES,
        default=DELIVERY_DELIVERED,
        help_text="Whether goods have been fully received.",
    )
    is_paid = models.BooleanField(
        default=False,
        help_text="True once the invoice has been fully settled.",
    )

    # ── Audit ──────────────────────────────────────────────────────────────────
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_deliveries",
        help_text="Staff member who logged this delivery.",
    )
    notes = models.TextField(
        blank=True,
        help_text="Any notes about this delivery (quality issues, shortages, etc.).",
    )

    def __str__(self):
        return f"{self.supplier.name} | {self.invoice_number or 'no inv#'} | {self.delivery_date}"

    class Meta:
        verbose_name = "Supplier Delivery"
        verbose_name_plural = "Supplier Deliveries"
        ordering = ["-delivery_date", "-created_at"]
        indexes = [
            models.Index(fields=["supplier", "is_paid"]),
            models.Index(fields=["store", "delivery_date"]),
        ]


# ── SupplierPayment ───────────────────────────────────────────────────────────

class SupplierPayment(BaseModel):
    """
    A payment made to a supplier to settle one or more deliveries.

    Payments are logged here as an immutable ledger entry.
    The outstanding balance is always: sum(deliveries) - sum(payments).

    A payment can be linked to a specific delivery (common case)
    or left unlinked if it covers multiple invoices (bulk payment).
    """

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name="payments",
        help_text="Supplier this payment was made to.",
    )
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="supplier_payments",
    )
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="supplier_payments",
    )

    # ── Payment details ────────────────────────────────────────────────────────
    delivery = models.ForeignKey(
        SupplierDelivery,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_records",
        help_text="Specific delivery this payment settles (leave blank for bulk payments).",
    )
    amount = models.PositiveIntegerField(
        help_text="Amount paid in TZS.",
    )
    payment_date = models.DateField(
        help_text="Date the payment was made.",
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default=METHOD_CASH,
        help_text="How the payment was made.",
    )
    reference = models.CharField(
        max_length=200,
        blank=True,
        help_text="Bank reference, cheque number, or mobile money ID.",
    )

    # ── Audit ──────────────────────────────────────────────────────────────────
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_supplier_payments",
        help_text="Staff member who logged this payment.",
    )
    notes = models.TextField(
        blank=True,
    )

    def __str__(self):
        return f"{self.supplier.name} | TZS {self.amount:,} | {self.payment_date}"

    class Meta:
        verbose_name = "Supplier Payment"
        verbose_name_plural = "Supplier Payments"
        ordering = ["-payment_date", "-created_at"]
        indexes = [
            models.Index(fields=["supplier", "payment_date"]),
        ]
