"""
apps/transactions/models.py

Data models for sales transactions (POS).

Referenced UI pages:
  - /pos                     → CartPanel, CartLineRow, payment method buttons
  - /transactions            → TransactionsPage (list with filters, day grouping)
  - /transactions/[id]       → TransactionDetailPage (line items, payment, timeline)
  - Dashboard recent txns    → last 8 transactions widget
  - Dashboard "Today summary"→ gross sales, net, profit aggregations

Model breakdown:
  Transaction     → one complete sale (header: total, method, cashier, till)
  TransactionLine → individual line items within a sale (product × qty × price)

Key data from UI (lib/data.ts):
  - methods: Cash | M-Pesa | Tigo Pesa | Bank | Credit
  - statuses: paid | credit | refunded | void
  - Transaction has: subtotal, discount, tax (18% VAT), total, cost, profit
  - Each line has: product ref, price snapshot, cost snapshot, qty
  - Payment method is stored, plus optional M-Pesa reference number
  - Till number stored: "Till #1", "Till #2", "Till #3"
  - Customer can be Walk-in (null) or a registered Customer

Price snapshots:
  We store price and cost AT THE TIME OF SALE on the TransactionLine.
  This is critical — product prices change over time, but historical
  transactions must reflect what was actually charged and cost.
"""

from django.conf import settings
from django.db import models

from apps.accounts.models import Store
from apps.core.models import BaseModel


# ── Transaction ───────────────────────────────────────────────────────────────

class Transaction(BaseModel):
    """
    A single completed sale at the point of sale.

    One transaction = one "ticket" = one customer visit.
    May contain multiple line items (products).

    From the UI, a transaction has:
      id (TXN-NNNN), ts, lines, subtotal, discountPct, discount,
      tax, total, cost, profit, customer, method, status,
      cashier, till, store, reference
    """

    # ── Store context ──────────────────────────────────────────────────────────
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="transactions",
        help_text="Store where this sale took place.",
    )

    # ── Human-readable ID ──────────────────────────────────────────────────────
    # The UI shows "TXN-2043" — this is a sequential display ID per store
    # The actual PK is a UUID, but we generate a display number for receipts
    txn_number = models.CharField(
        max_length=30,
        unique=True,
        help_text="Human-readable transaction number (TXN-NNNN) shown on receipts.",
    )

    # ── Payment ────────────────────────────────────────────────────────────────
    METHOD_CASH     = "Cash"
    METHOD_MPESA    = "M-Pesa"
    METHOD_TIGO     = "Tigo Pesa"
    METHOD_BANK     = "Bank"
    METHOD_CREDIT   = "Credit"
    METHOD_CHOICES = [
        (METHOD_CASH,   "Cash"),
        (METHOD_MPESA,  "M-Pesa"),
        (METHOD_TIGO,   "Tigo Pesa"),
        (METHOD_BANK,   "Bank"),
        (METHOD_CREDIT, "Credit (on tab)"),
    ]
    payment_method = models.CharField(
        max_length=20,
        choices=METHOD_CHOICES,
        default=METHOD_CASH,
        help_text="How the customer paid.",
    )

    # M-Pesa / Tigo Pesa reference number (e.g. "QGT5K3AB")
    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Mobile money confirmation code or bank reference.",
    )

    # ── Status ─────────────────────────────────────────────────────────────────
    STATUS_PAID     = "paid"
    STATUS_CREDIT   = "credit"    # customer owes — recorded in credits app
    STATUS_REFUNDED = "refunded"
    STATUS_VOID     = "void"      # cancelled before completion
    STATUS_CHOICES = [
        (STATUS_PAID,     "Paid"),
        (STATUS_CREDIT,   "On Credit"),
        (STATUS_REFUNDED, "Refunded"),
        (STATUS_VOID,     "Void"),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PAID,
        help_text="Transaction status.",
    )

    # ── Amounts (TZS integers) ─────────────────────────────────────────────────
    # Sum of (line.price × line.qty) before discount
    subtotal = models.PositiveIntegerField(
        default=0,
        help_text="Sum of all line totals before discount (TZS).",
    )

    # Discount as a percentage (0–100)
    discount_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Discount percentage applied (e.g. 5.00 for 5%).",
    )

    # Absolute discount amount in TZS (= subtotal × discount_pct / 100)
    discount_amount = models.PositiveIntegerField(
        default=0,
        help_text="Absolute discount amount in TZS.",
    )

    # VAT at 18% on (subtotal - discount)
    tax_amount = models.PositiveIntegerField(
        default=0,
        help_text="VAT (18%) amount in TZS.",
    )

    # Total the customer pays (subtotal - discount + tax)
    total = models.PositiveIntegerField(
        default=0,
        help_text="Net total charged to customer (TZS).",
    )

    # Total cost of goods in this sale (sum of line.cost × line.qty)
    cost_total = models.PositiveIntegerField(
        default=0,
        help_text="Total cost of goods sold (TZS).",
    )

    # Gross profit = total - cost_total - tax_amount
    # (profit is what we actually keep after tax and COGS)
    profit = models.IntegerField(
        default=0,
        help_text="Gross profit on this transaction (TZS). Can be negative.",
    )

    # ── Staff / Register ───────────────────────────────────────────────────────
    # The cashier who processed this transaction
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        help_text="Staff member who processed this sale.",
    )

    # Which till/register was used: "Till #1", "Till #2", "Till #3"
    till_number = models.CharField(
        max_length=20,
        default="Till #1",
        help_text="Till / register number, e.g. 'Till #2'.",
    )

    # ── Customer ───────────────────────────────────────────────────────────────
    # Walk-in customers have no customer record (null)
    # Named customers are linked to the customers app Customer model
    # We use a generic FK approach: store name/phone for flexibility
    customer_name = models.CharField(
        max_length=200,
        default="Walk-in",
        help_text="Customer display name (or 'Walk-in' if anonymous).",
    )

    customer_phone = models.CharField(
        max_length=30,
        blank=True,
        help_text="Customer phone number (+255 7XX XXX XXX).",
    )

    # Optional FK to registered customer profile (null for walk-in)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        help_text="Linked customer profile (null for walk-in customers).",
    )

    # ── Channel ────────────────────────────────────────────────────────────────
    # In MVP all sales come from the counter. Future: mobile, online, etc.
    CHANNEL_COUNTER = "counter"
    CHANNEL_CHOICES = [(CHANNEL_COUNTER, "Counter")]
    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        default=CHANNEL_COUNTER,
        help_text="Sales channel (counter, mobile, online, etc.).",
    )

    # Notes (optional, for refund reasons etc.)
    notes = models.TextField(
        blank=True,
        help_text="Optional notes (e.g. refund reason).",
    )

    def __str__(self):
        return f"{self.txn_number} | {self.customer_name} | TZS {self.total:,} | {self.status}"

    @property
    def item_count(self):
        """Total units sold across all lines."""
        return sum(line.qty for line in self.lines.all())

    @property
    def sku_count(self):
        """Number of distinct SKUs in this transaction."""
        return self.lines.count()

    class Meta:
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"
        ordering = ["-created_at"]
        indexes = [
            # Fast lookup by store + date (used for daily summaries)
            models.Index(fields=["store", "created_at"]),
            # Fast lookup by status (credit tab queries)
            models.Index(fields=["status"]),
        ]


# ── Transaction Line ──────────────────────────────────────────────────────────

class TransactionLine(BaseModel):
    """
    One line item within a transaction (one product × qty).

    CRITICAL: price and cost are snapshots taken AT THE TIME OF SALE.
    Product prices can change — we never recalculate from the current Product.

    From the UI:
      { id, name, sku, price, cost, qty }
      line_total = price × qty
    """

    # Parent transaction
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name="lines",
        help_text="Parent transaction this line belongs to.",
    )

    # Product reference (kept for linking back to inventory)
    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transaction_lines",
        help_text="Product sold (null if product was later deleted).",
    )

    # ── Price snapshots (stored at time of sale — NEVER recalculated) ─────────
    product_name = models.CharField(
        max_length=300,
        help_text="Product name at time of sale (snapshot).",
    )

    product_sku = models.CharField(
        max_length=50,
        help_text="Product SKU at time of sale (snapshot).",
    )

    # Unit selling price in TZS (snapshot)
    unit_price = models.PositiveIntegerField(
        help_text="Selling price per unit at time of sale (TZS).",
    )

    # Unit cost in TZS (snapshot — used for profit calculation)
    unit_cost = models.PositiveIntegerField(
        default=0,
        help_text="Cost per unit at time of sale (TZS).",
    )

    # Number of units sold
    qty = models.PositiveIntegerField(
        default=1,
        help_text="Quantity sold.",
    )

    def __str__(self):
        return f"{self.product_name} × {self.qty} @ TZS {self.unit_price:,}"

    @property
    def line_total(self):
        """Total for this line: unit_price × qty."""
        return self.unit_price * self.qty

    @property
    def line_cost(self):
        """Total cost for this line: unit_cost × qty."""
        return self.unit_cost * self.qty

    @property
    def line_profit(self):
        """Gross profit for this line."""
        return self.line_total - self.line_cost

    class Meta:
        verbose_name = "Transaction Line"
        verbose_name_plural = "Transaction Lines"
        ordering = ["created_at"]
