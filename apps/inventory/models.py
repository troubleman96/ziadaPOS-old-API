"""
apps/inventory/models.py

Data models for product inventory management.

Model breakdown:
  Category        → product groupings (Grocery, Household, Beverage, …)
  Product         → individual SKU with price, cost, stock levels
  StockAdjustment → audit log for every stock change (sale, restock, manual)

Supplier model lives in apps.suppliers — Product.supplier is a cross-app FK.
"""

from django.conf import settings
from django.db import models

from apps.accounts.models import Store
from apps.core.models import BaseModel


# ── Category ──────────────────────────────────────────────────────────────────

class Category(BaseModel):
    """
    Product category — used for filtering in the UI category pills.

    From the UI: All | Grocery | Household | Beverage | Cosmetics | Bakery | Snacks
    """

    # Category name shown in the filter pills
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Category name, e.g. 'Grocery'. Must be unique.",
    )

    # Optional description for admin clarity
    description = models.TextField(
        blank=True,
        help_text="Optional description of what belongs in this category.",
    )

    # Sort order for UI display (lower = shown first)
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Display order in filter pills (0 = first).",
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ["sort_order", "name"]


# ── Product ───────────────────────────────────────────────────────────────────

class Product(BaseModel):
    """
    A sellable product / SKU.

    Maps directly to the UI's INVENTORY array and POS_PRODUCTS.
    One Product exists globally; stock levels are tracked per-store
    via the 'stock', 'min', 'max' fields (MVP: single-store, so these
    live directly on the product — multi-store would use a StockLevel table).

    Pricing note:
      - price: selling price (what the customer pays), includes VAT
      - cost:  purchase/landed cost (what we paid the supplier)
      - margin = (price - cost) / price × 100
    """

    # The store this product belongs to (MVP: single-store scoping)
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="products",
        help_text="Store this product is stocked in.",
    )

    # ── Identity ───────────────────────────────────────────────────────────────
    # Human-readable name shown in the UI
    name = models.CharField(
        max_length=300,
        help_text="Product name, e.g. 'Unga wa Sembe 10kg'.",
    )

    # Stock Keeping Unit — unique short code for inventory tracking
    sku = models.CharField(
        max_length=50,
        help_text="SKU code, e.g. 'UWS-10'. Unique within a store.",
    )

    # Barcode (EAN-13 or similar) for scanner input in POS
    barcode = models.CharField(
        max_length=100,
        blank=True,
        help_text="Barcode number (EAN-13), e.g. '6160100012413'.",
    )

    # ── Classification ─────────────────────────────────────────────────────────
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        help_text="Product category for filtering.",
    )

    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        help_text="Primary supplier / vendor for this product.",
    )

    # Unit of measure shown in inventory ("bag", "pcs", "jerry", "btl", etc.)
    unit = models.CharField(
        max_length=20,
        default="pcs",
        help_text="Unit of measure: pcs, bag, btl, jerry, pack, tub, etc.",
    )

    # ── Pricing (TZS, stored as integers — no sub-units) ──────────────────────
    # Selling price (what the customer pays, VAT-inclusive)
    price = models.PositiveIntegerField(
        help_text="Selling price in TZS (VAT-inclusive), e.g. 28500.",
    )

    # Cost / landed price (what we paid the supplier, excl. VAT)
    cost = models.PositiveIntegerField(
        help_text="Purchase / landed cost in TZS, e.g. 22000.",
    )

    # ── Stock levels ───────────────────────────────────────────────────────────
    # Current quantity on hand
    stock = models.IntegerField(
        default=0,
        help_text="Current units in stock. Can go negative (oversell allowed).",
    )

    # Reorder point — trigger low stock alert when stock <= min
    min_stock = models.PositiveIntegerField(
        default=0,
        help_text="Reorder point. Low stock alert fires when stock ≤ this value.",
    )

    # Maximum stock capacity — upper limit for the stock bar visualisation
    max_stock = models.PositiveIntegerField(
        default=100,
        help_text="Maximum stock capacity (used for UI stock bar scale).",
    )

    # ── Weekly velocity (used for AI restock suggestions) ─────────────────────
    # Average units sold per week — updated nightly by analytics service
    weekly_sold = models.PositiveIntegerField(
        default=0,
        help_text="Average units sold per week (updated nightly).",
    )

    # Last restock date — shown in inventory detail
    last_restock_at = models.DateField(
        null=True,
        blank=True,
        help_text="Date of the most recent stock replenishment.",
    )

    # ── UI presentation ────────────────────────────────────────────────────────
    # Color scheme key for product avatar/thumbnail in UI
    # Values: indigo, amber, rose, lime, emerald, violet, cyan
    color = models.CharField(
        max_length=20,
        default="indigo",
        help_text="Color scheme key for the product avatar (indigo/amber/rose/…).",
    )

    # Whether this product is active and can be sold
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive products are hidden from POS and inventory.",
    )

    def __str__(self):
        return f"{self.name} ({self.sku})"

    # ── Computed properties ────────────────────────────────────────────────────

    @property
    def margin_pct(self):
        """Gross margin as a percentage: (price - cost) / price × 100."""
        if self.price == 0:
            return 0.0
        return round((self.price - self.cost) / self.price * 100, 1)

    @property
    def stock_status(self):
        """
        Stock status as a string matching the UI status labels:
          'out'      → stock == 0
          'critical' → stock <= min_stock * 0.4
          'low'      → stock <= min_stock
          'active'   → everything else
        """
        if self.stock == 0:
            return "out"
        if self.min_stock and self.stock <= self.min_stock * 0.4:
            return "critical"
        if self.min_stock and self.stock <= self.min_stock:
            return "low"
        return "active"

    @property
    def days_of_stock(self):
        """
        Estimated days of stock remaining based on weekly velocity.
        Returns None if weekly_sold is 0 (unknown velocity).
        """
        if not self.weekly_sold:
            return None
        daily_rate = self.weekly_sold / 7
        return round(self.stock / daily_rate) if daily_rate else None

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        ordering = ["name"]
        # SKU must be unique within a store
        unique_together = [("store", "sku")]


# ── Stock Adjustment ──────────────────────────────────────────────────────────

class StockAdjustment(BaseModel):
    """
    Audit log for every change to a product's stock level.

    Created automatically when:
      - A sale is completed (quantity decreases)
      - A restock is recorded (quantity increases)
      - A manual adjustment is made (can be + or -)
      - A refund is processed (quantity increases back)

    This gives us a complete, immutable history of all stock movements.
    The AI can use this to identify stockout patterns.
    """

    # Which product was adjusted
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stock_adjustments",
        help_text="Product whose stock changed.",
    )

    # Type of adjustment
    TYPE_SALE     = "sale"       # reduced by a POS transaction
    TYPE_RESTOCK  = "restock"    # increased by a supplier delivery
    TYPE_MANUAL   = "manual"     # manual correction by manager
    TYPE_REFUND   = "refund"     # returned to stock after a refund
    TYPE_DAMAGE   = "damage"     # written off (damaged / expired)
    TYPE_OPENING  = "opening"    # initial stock when product is created
    TYPE_CHOICES = [
        (TYPE_SALE,    "Sale"),
        (TYPE_RESTOCK, "Restock"),
        (TYPE_MANUAL,  "Manual Adjustment"),
        (TYPE_REFUND,  "Refund"),
        (TYPE_DAMAGE,  "Damage / Write-off"),
        (TYPE_OPENING, "Opening Stock"),
    ]
    adjustment_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        help_text="What caused this stock change.",
    )

    # How many units changed (positive = stock increased, negative = decreased)
    quantity_change = models.IntegerField(
        help_text="Units added (+) or removed (-) from stock.",
    )

    # Stock level BEFORE this adjustment (for audit trail)
    quantity_before = models.IntegerField(
        help_text="Stock level before this adjustment.",
    )

    # Stock level AFTER this adjustment
    quantity_after = models.IntegerField(
        help_text="Stock level after this adjustment.",
    )

    # Optional reference (e.g. transaction ID, purchase order number)
    reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Reference document (TXN ID, PO number, etc.).",
    )

    # Who made this adjustment
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_adjustments",
        help_text="User who performed this adjustment.",
    )

    # Optional note explaining the reason (for manual adjustments)
    note = models.TextField(
        blank=True,
        help_text="Reason for adjustment (required for manual adjustments).",
    )

    def __str__(self):
        direction = "+" if self.quantity_change >= 0 else ""
        return (
            f"{self.product.name} | {direction}{self.quantity_change} "
            f"| {self.adjustment_type} | {self.created_at.date()}"
        )

    class Meta:
        verbose_name = "Stock Adjustment"
        verbose_name_plural = "Stock Adjustments"
        ordering = ["-created_at"]
