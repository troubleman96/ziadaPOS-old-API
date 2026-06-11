"""
apps/customers/models.py

Customer model for the Ziada POS.

Referenced UI pages examined before building:
  /customers      → Customer list (segmented, sortable)
  /customers/[id] → Customer detail (full history)
  /credits        → CreditCustomer references this model via one-to-one or FK
  /pos            → CompleteSaleView accepts optional customer_id

What a Customer represents:
  A recurring buyer registered in the store's directory.
  Walk-in customers are NOT stored here — they live on Transaction.customer_name only.

Key design decisions:
  - Segment is stored, not computed, so staff can manually override it.
    A nightly job or signal can auto-update segments based on spend thresholds.
  - total_spent, last_visit, avg_ticket are denormalized cache fields updated
    whenever a transaction is created or refunded.
  - avatar_hue is a 0-360 integer used by the frontend to render the avatar
    gradient without fetching an image.
  - open_credit is a cached sum of unpaid CreditTab balances — kept in sync
    by CreditTab and CreditPayment signals.
"""

from django.db import models

from apps.accounts.models import Store, User
from apps.core.models import BaseModel


class Customer(BaseModel):
    """
    A registered customer of a store.

    Used for:
      - Credit sales (linked from Transaction.customer and CreditTab)
      - Customer directory in /customers page
      - AI recommendations using spend history
      - Segment-based targeting

    Table: customers_customer
    """

    # ── Segment choices ───────────────────────────────────────────────────────
    SEGMENT_VIP        = "VIP"
    SEGMENT_REGULAR    = "Regular"
    SEGMENT_OCCASIONAL = "Occasional"
    SEGMENT_NEW        = "New"

    SEGMENT_CHOICES = [
        (SEGMENT_VIP,        "VIP"),
        (SEGMENT_REGULAR,    "Regular"),
        (SEGMENT_OCCASIONAL, "Occasional"),
        (SEGMENT_NEW,        "New"),
    ]

    # ── Core fields ───────────────────────────────────────────────────────────

    # The store this customer belongs to.
    # Customers are scoped to a store — not shared across stores.
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="customers",
        help_text="Store this customer belongs to.",
    )

    # Full name as the customer wants it displayed.
    name = models.CharField(
        max_length=200,
        help_text="Customer's full name.",
    )

    # Phone number — used for WhatsApp reminders, search, and display.
    # Not unique because the same phone can appear in different stores in theory,
    # but within a store we enforce uniqueness via unique_together.
    phone = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Phone in international format, e.g. +255 712 345 678.",
    )

    # Optional email for future receipts
    email = models.EmailField(
        blank=True,
        default="",
        help_text="Email address (optional).",
    )

    # ── Segmentation ──────────────────────────────────────────────────────────

    # Customer segment — updated by staff or periodic background task.
    # Thresholds (customisable): VIP > 1M TZS, Regular > 200k, New < 60 days.
    segment = models.CharField(
        max_length=20,
        choices=SEGMENT_CHOICES,
        default=SEGMENT_NEW,
        help_text="Loyalty segment assigned to this customer.",
    )

    # ── Denormalised stats (cache fields) ─────────────────────────────────────
    # These are updated every time a transaction is completed or refunded.
    # Saves expensive aggregations in real-time list views.

    # Lifetime total spend (TZS, integer)
    total_spent = models.PositiveIntegerField(
        default=0,
        help_text="Lifetime total amount spent by this customer (TZS, cached).",
    )

    # Date of last purchase visit
    last_visit = models.DateField(
        null=True,
        blank=True,
        help_text="Date of last completed transaction.",
    )

    # Average ticket size (TZS, integer)
    avg_ticket = models.PositiveIntegerField(
        default=0,
        help_text="Average transaction total (TZS, cached).",
    )

    # Open credit (outstanding balance, TZS)
    # Updated by CreditTab creation and CreditPayment.
    open_credit = models.PositiveIntegerField(
        default=0,
        help_text="Current outstanding credit balance (TZS, cached).",
    )

    # Maximum credit allowed for this customer (TZS). Null = no limit.
    credit_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum credit allowed (TZS). Null means no limit.",
    )

    # ── Display ───────────────────────────────────────────────────────────────

    # Hue (0-360) for the avatar gradient — set randomly on creation.
    # Used by the frontend to render a colourful avatar without an image.
    avatar_hue = models.PositiveSmallIntegerField(
        default=200,
        help_text="0–360 colour hue for avatar gradient.",
    )

    # Optional short notes visible on the customer card
    notes = models.TextField(
        blank=True,
        default="",
        help_text="Internal notes about this customer.",
    )

    # Soft-delete — instead of removing, mark inactive so history is preserved.
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive customers are hidden from lists but not deleted.",
    )

    class Meta:
        """Meta options for the Customer model."""
        db_table = "customers_customer"
        ordering = ["-total_spent"]  # Show VIP customers first in lists
        verbose_name = "Customer"
        verbose_name_plural = "Customers"

        # One phone per store (allows same phone across stores)
        unique_together = [("store", "phone")]

        indexes = [
            # Searching by name and phone — the most common filter
            models.Index(fields=["store", "is_active"], name="idx_customer_store_active"),
            models.Index(fields=["segment"], name="idx_customer_segment"),
        ]

    def __str__(self):
        return f"{self.name} ({self.store.name})"

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def initials(self) -> str:
        """
        Two-letter initials for the avatar fallback.
        'Fatuma Ally' → 'FA'
        """
        parts = self.name.split()
        return "".join(p[0].upper() for p in parts[:2])

    @property
    def has_open_credit(self) -> bool:
        """True if this customer has any outstanding credit balance."""
        return self.open_credit > 0
