"""
apps/subscriptions/models.py

Subscription billing system for Ziada POS.

Business rules (as specified):
  - New account gets a 1-week trial at 10,000 TZS.
  - Base package includes 3 stores.
  - Monthly plan:    25,000 TZS/month
  - 6-month plan:   23,000 TZS/month × 6  = 138,000 TZS total
  - Yearly plan:    22,000 TZS/month × 12 = 264,000 TZS total
  - Extra store:    12,000 TZS/store/month (paid separately)

Plans are created and priced by the Cameltech admin panel.
Subscriptions are linked 1:1 with an Organisation.

Model hierarchy:
  SubscriptionPlan  ← admin-configurable pricing tiers
  Subscription      ← one active subscription per Organisation
"""

from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


# ── Subscription Plan (admin-configurable) ─────────────────────────────────────

class SubscriptionPlan(BaseModel):
    """
    A pricing tier that Cameltech admins create and manage via the admin panel.

    Examples:
      - Monthly:   price_per_month=25000, duration_months=1
      - 6-Month:   price_per_month=23000, duration_months=6
      - Yearly:    price_per_month=22000, duration_months=12

    All amounts are in TZS (no decimals — TZS has no sub-unit).
    """

    name = models.CharField(
        max_length=100,
        help_text="Display name shown to owners, e.g. 'Monthly' or '6-Month Package'.",
    )

    slug = models.SlugField(
        max_length=50,
        unique=True,
        help_text="URL-safe identifier, e.g. 'monthly', 'half-yearly', 'yearly'.",
    )

    description = models.TextField(
        blank=True,
        help_text="Optional marketing description of this plan.",
    )

    # Billing amount per month (TZS integer)
    price_per_month = models.PositiveIntegerField(
        help_text="Monthly price in TZS, e.g. 25000 for 25,000 TZS/month.",
    )

    # How many months this plan covers (1 = monthly, 6 = half-year, 12 = yearly)
    duration_months = models.PositiveSmallIntegerField(
        default=1,
        help_text="Number of months this plan covers per payment cycle.",
    )

    # How many stores are bundled in the base price (default 3)
    included_stores = models.PositiveSmallIntegerField(
        default=3,
        help_text="Number of stores included in the base price.",
    )

    # Price per extra store per month (TZS)
    extra_store_price_per_month = models.PositiveIntegerField(
        default=12000,
        help_text="Cost per additional store per month, in TZS.",
    )

    # Admins can deactivate a plan without deleting it
    is_active = models.BooleanField(
        default=True,
        help_text="Only active plans are shown to prospective owners.",
    )

    # Display ordering on the pricing page
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Display order (lower = shown first).",
    )

    def __str__(self):
        return f"{self.name} — {self.price_per_month:,} TZS/mo × {self.duration_months}mo"

    @property
    def total_price(self):
        """Total amount billed per cycle (price × months)."""
        return self.price_per_month * self.duration_months

    @property
    def extra_store_price_total(self):
        """Extra store cost for the full cycle duration."""
        return self.extra_store_price_per_month * self.duration_months

    class Meta:
        verbose_name = "Subscription Plan"
        verbose_name_plural = "Subscription Plans"
        ordering = ["sort_order", "price_per_month"]


# ── Subscription (per Organisation) ───────────────────────────────────────────

class Subscription(BaseModel):
    """
    Tracks the active (or most recent) subscription for an Organisation.

    Lifecycle:
      1. Registration → status=trial, is_trial=True, end_date = now + 7 days
      2. Owner pays trial fee (10,000 TZS) → admin marks trial payment confirmed
      3. Owner selects a plan and pays → admin creates new Subscription (status=active)
      4. Subscription expires → status=expired, POS access blocked

    One Organisation should have at most ONE active subscription at a time.
    Historical subscriptions are kept for audit purposes.
    """

    STATUS_TRIAL     = "trial"
    STATUS_ACTIVE    = "active"
    STATUS_EXPIRED   = "expired"
    STATUS_CANCELLED = "cancelled"
    STATUS_PENDING   = "pending_payment"   # created but payment not confirmed
    STATUS_CHOICES = [
        (STATUS_TRIAL,     "Trial"),
        (STATUS_ACTIVE,    "Active"),
        (STATUS_EXPIRED,   "Expired"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_PENDING,   "Pending Payment"),
    ]

    organisation = models.ForeignKey(
        "accounts.Organisation",
        on_delete=models.CASCADE,
        related_name="subscriptions",
        help_text="The organisation this subscription belongs to.",
    )

    plan = models.ForeignKey(
        SubscriptionPlan,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subscriptions",
        help_text="The plan tier chosen. Null during trial.",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    # Date range this subscription covers
    start_date = models.DateField(help_text="Subscription start date.")
    end_date   = models.DateField(help_text="Subscription end date (access expires at midnight).")

    # Trial flag — true only for the initial 7-day trial
    is_trial = models.BooleanField(
        default=False,
        help_text="True if this is the initial 1-week trial subscription.",
    )

    # Trial one-off fee (10,000 TZS) — separate from plan pricing
    trial_fee = models.PositiveIntegerField(
        default=10000,
        help_text="One-time trial fee in TZS (default 10,000).",
    )

    # Number of additional stores beyond the plan's included_stores
    extra_stores = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of additional paid stores beyond the plan's bundled quota.",
    )

    # Payment tracking
    amount_paid = models.PositiveIntegerField(
        default=0,
        help_text="Amount actually received in TZS.",
    )
    payment_reference = models.CharField(
        max_length=200,
        blank=True,
        help_text="M-Pesa code, bank ref, or other payment identifier.",
    )
    payment_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the payment was received.",
    )

    # Who activated this subscription (Cameltech admin)
    activated_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activated_subscriptions",
        help_text="Cameltech admin who confirmed the payment.",
    )

    notes = models.TextField(
        blank=True,
        help_text="Internal notes (e.g. 'payment confirmed via WhatsApp').",
    )

    def __str__(self):
        return f"{self.organisation.name} — {self.get_status_display()} ({self.start_date} → {self.end_date})"

    @property
    def is_active_now(self):
        """True if this subscription grants current access."""
        today = timezone.now().date()
        return self.status in (self.STATUS_TRIAL, self.STATUS_ACTIVE) and self.end_date >= today

    @property
    def days_remaining(self):
        """How many days until this subscription expires."""
        today = timezone.now().date()
        delta = self.end_date - today
        return max(0, delta.days)

    @property
    def max_stores_allowed(self):
        """Total stores allowed: plan bundled + extra paid stores."""
        base = self.plan.included_stores if self.plan else 3
        return base + self.extra_stores

    @property
    def total_amount_due(self):
        """What the organisation owes for this subscription cycle."""
        if self.is_trial:
            return self.trial_fee
        if not self.plan:
            return 0
        extra_cost = self.extra_stores * self.plan.extra_store_price_per_month * self.plan.duration_months
        return self.plan.total_price + extra_cost

    class Meta:
        verbose_name = "Subscription"
        verbose_name_plural = "Subscriptions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organisation", "status"]),
            models.Index(fields=["end_date"]),
        ]
