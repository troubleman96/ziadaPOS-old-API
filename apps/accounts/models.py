"""
apps/accounts/models.py

Data models for user accounts, organisations, and stores.

Referenced UI pages:
  - Sidenav: shows store switcher ("Duka Kuu · Kariakoo · 3 stores")
  - Sidenav footer: shows logged-in user ("Hamisi Mwakapaga · Owner")
  - Dashboard: "Good afternoon, Hamisi" personalisation
  - AI credits: "2,418 / 5,000" shown in sidenav footer
  - Profile page: phone/email verification reminder banners

Model hierarchy:
  Organisation  (the registered business)
    └── Store   (physical locations — 3 bundled, extras paid)
         └── User (staff member assigned to one store)
  User (owner role links directly to Organisation AND may have a main store)

Role definitions:
  admin  → Cameltech system admin (us). Full platform access.
  owner  → Registered business owner. Manages their org + all stores.
  staff  → Store employee. Scoped to one store, permissions set by owner.
"""

import random

from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from apps.accounts.tanzania import BUSINESS_TYPE_CHOICES, REGION_CHOICES
from apps.core.models import BaseModel


# ── Organisation ──────────────────────────────────────────────────────────────

class Organisation(BaseModel):
    """
    The top-level entity — a registered business that owns one or more stores.

    Created automatically during owner registration together with:
      - The owner User record
      - The main Store record
      - A trial Subscription record

    In the UI: "Duka Kuu" is the organisation name shown in the sidenav.
    """

    name = models.CharField(
        max_length=200,
        help_text="Trading/shop name of the organisation, e.g. 'Duka Kuu'.",
    )

    legal_name = models.CharField(
        max_length=300,
        blank=True,
        help_text="Full legal registered name (may differ from trading name).",
    )

    tin = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="TIN",
        help_text="Tanzania TRA Tax Identification Number (printed on receipts).",
    )

    # Business type — determines which category presets are seeded at registration
    business_type = models.CharField(
        max_length=20,
        choices=BUSINESS_TYPE_CHOICES,
        default="retail",
        help_text="Type of business (determines pre-configured POS categories).",
    )

    # Tanzania administrative region
    region = models.CharField(
        max_length=100,
        choices=REGION_CHOICES,
        blank=True,
        help_text="Tanzania region where this business is based.",
    )

    country = models.CharField(
        max_length=2,
        default="TZ",
        help_text="ISO 3166-1 alpha-2 country code.",
    )

    currency = models.CharField(
        max_length=3,
        default="TZS",
        help_text="ISO 4217 currency code.",
    )

    # Maximum stores this organisation can have (3 bundled + extras paid via Subscription)
    max_stores = models.PositiveSmallIntegerField(
        default=3,
        help_text="Maximum stores allowed. Updated by subscription system when extra stores are purchased.",
    )

    ai_credits_monthly = models.PositiveIntegerField(
        default=5000,
        help_text="Total AI credits allocated per month.",
    )

    # Plan tier — synced from Subscription.status when admin activates
    PLAN_FREE       = "free"
    PLAN_PRO        = "pro"
    PLAN_ENTERPRISE = "enterprise"
    PLAN_CHOICES = [
        (PLAN_FREE,       "Free / Trial"),
        (PLAN_PRO,        "Pro"),
        (PLAN_ENTERPRISE, "Enterprise"),
    ]
    plan = models.CharField(
        max_length=20,
        choices=PLAN_CHOICES,
        default=PLAN_FREE,
        help_text="Subscription plan tier. Synced by the subscription system.",
    )

    # Trial expiry — kept for fast subscription checks without joining Subscription table
    trial_ends_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Trial expiry datetime (set on registration, null after upgrade).",
    )

    def __str__(self):
        return self.name

    @property
    def active_subscription(self):
        """Return the latest active subscription, or None."""
        return (
            self.subscriptions
            .filter(status__in=("trial", "active"))
            .order_by("-created_at")
            .first()
        )

    @property
    def has_active_subscription(self):
        sub = self.active_subscription
        return sub is not None and sub.is_active_now

    class Meta:
        verbose_name = "Organisation"
        verbose_name_plural = "Organisations"
        ordering = ["name"]


# ── Store ─────────────────────────────────────────────────────────────────────

class Store(BaseModel):
    """
    A physical store location belonging to an Organisation.

    Owners get 3 stores bundled in their base package. Additional stores
    cost 12,000 TZS/month each and must be approved by a Cameltech admin.

    In the UI:
      - Sidenav: "Kariakoo" (the area) with store switcher
      - Receipts: "DUKA KUU — KARIAKOO" printed at top
    """

    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="stores",
        help_text="Organisation this store belongs to.",
    )

    name = models.CharField(
        max_length=200,
        help_text="Store name shown in the UI, e.g. 'Kariakoo Branch'.",
    )

    code = models.CharField(
        max_length=10,
        blank=True,
        help_text="Short store code for transaction IDs, e.g. 'KRC' → TXN-KRC-2043.",
    )

    address = models.TextField(
        blank=True,
        help_text="Full physical address of the store.",
    )

    area = models.CharField(
        max_length=100,
        blank=True,
        help_text="Area / neighbourhood, e.g. 'Kariakoo'.",
    )

    phone = models.CharField(
        max_length=30,
        blank=True,
        help_text="Store contact phone number.",
    )

    till_count = models.PositiveSmallIntegerField(
        default=1,
        help_text="Number of POS tills/registers in this store.",
    )

    email = models.EmailField(
        blank=True,
        help_text="Store contact email address.",
    )

    open_hours = models.CharField(
        max_length=50,
        blank=True,
        default="7:00 AM – 9:00 PM",
        help_text="Opening hours label shown in the UI.",
    )

    color = models.CharField(
        max_length=20,
        blank=True,
        default="#6366f1",
        help_text="Hex colour for store avatar and sparkline.",
    )

    # Whether this is the first (main) store created on registration
    is_main_store = models.BooleanField(
        default=False,
        help_text="True for the primary store created during registration.",
    )

    STATUS_OPEN   = "open"
    STATUS_CLOSED = "closed"
    STATUS_PAUSED = "paused"
    STATUS_CHOICES = [
        (STATUS_OPEN,   "Open"),
        (STATUS_CLOSED, "Closed"),
        (STATUS_PAUSED, "Paused"),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Active stores appear in the store switcher.",
    )

    def __str__(self):
        return f"{self.organisation.name} — {self.name}"

    @property
    def display_name(self):
        return f"{self.organisation.name} — {self.name}"

    class Meta:
        verbose_name = "Store"
        verbose_name_plural = "Stores"
        ordering = ["organisation__name", "name"]
        unique_together = [("organisation", "name")]


# ── User (custom auth model) ──────────────────────────────────────────────────

phone_validator = RegexValidator(
    regex=r"^\d{10}$",
    message="Enter a valid 10-digit phone number (e.g. 0712345678).",
)


class User(AbstractUser, BaseModel):
    """
    Custom User model for Ziada POS.

    Login: phone number + password (not username).
    Username is auto-set to the phone number on save to satisfy AbstractUser.

    Role hierarchy:
      admin  → Cameltech platform admin. Full access everywhere.
      owner  → Registered business owner. Manages their own organisation + stores.
      staff  → Store employee. Scoped to one store, with owner-configured permissions.

    In the UI (sidenav footer):
      "Hamisi Mwakapaga · Owner"   → full_name + role
      Avatar "HM"                  → initials from name
    """

    # ── Roles ──────────────────────────────────────────────────────────────────
    ROLE_ADMIN = "admin"   # Cameltech system admin
    ROLE_OWNER = "owner"   # Registered business owner
    ROLE_STAFF = "staff"   # Store employee

    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin (Cameltech)"),
        (ROLE_OWNER, "Owner"),
        (ROLE_STAFF, "Staff"),
    ]
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_STAFF,
        help_text="User role determines API access level.",
    )

    # ── Phone (login field) ────────────────────────────────────────────────────
    # Phone is the primary login credential — must be unique and exactly 10 digits.
    # Username is auto-synced to phone on save so Django's AbstractUser is satisfied.
    phone = models.CharField(
        max_length=10,
        unique=True,
        validators=[phone_validator],
        help_text="10-digit Tanzanian phone number used to log in (e.g. 0712345678).",
    )

    # ── Email (optional) ───────────────────────────────────────────────────────
    # Override AbstractUser's required email — email is optional for TZ market.
    email = models.EmailField(
        blank=True,
        unique=True,
        null=True,
        default=None,
        help_text="Optional email address. Must be unique if provided.",
    )

    # ── Organisation link (owners span all stores; staff is scoped via store FK) ─
    organisation = models.ForeignKey(
        Organisation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="members",
        help_text="Direct organisation link set for owner-role users.",
    )

    # ── Store assignment (staff are scoped to one store) ───────────────────────
    store = models.ForeignKey(
        Store,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staff",
        help_text="Primary store this user works at. Required for staff, optional for owners.",
    )

    # ── Avatar colour ──────────────────────────────────────────────────────────
    avatar_hue = models.PositiveSmallIntegerField(
        default=260,
        help_text="Hue (0–360) for avatar background gradient.",
    )

    # ── Shift ──────────────────────────────────────────────────────────────────
    SHIFT_MORNING  = "morning"
    SHIFT_EVENING  = "evening"
    SHIFT_FULL_DAY = "full_day"
    SHIFT_WEEKEND  = "weekend"
    SHIFT_CHOICES = [
        (SHIFT_MORNING,  "Morning (7am–2pm)"),
        (SHIFT_EVENING,  "Evening (2pm–9pm)"),
        (SHIFT_FULL_DAY, "Full day (7am–7pm)"),
        (SHIFT_WEEKEND,  "Weekend (Sat–Sun)"),
    ]
    shift = models.CharField(
        max_length=20,
        choices=SHIFT_CHOICES,
        default=SHIFT_MORNING,
    )

    # ── Employment status ──────────────────────────────────────────────────────
    EMPLOYMENT_ACTIVE   = "active"
    EMPLOYMENT_ON_LEAVE = "on_leave"
    EMPLOYMENT_INACTIVE = "inactive"
    EMPLOYMENT_STATUS_CHOICES = [
        (EMPLOYMENT_ACTIVE,   "Active"),
        (EMPLOYMENT_ON_LEAVE, "On leave"),
        (EMPLOYMENT_INACTIVE, "Inactive"),
    ]
    employment_status = models.CharField(
        max_length=20,
        choices=EMPLOYMENT_STATUS_CHOICES,
        default=EMPLOYMENT_ACTIVE,
    )

    # ── POS PIN ────────────────────────────────────────────────────────────────
    pin = models.CharField(
        max_length=4,
        blank=True,
        help_text="4-digit POS access PIN.",
    )

    # ── Per-staff permissions (owner can toggle these for each staff member) ───
    can_refund       = models.BooleanField(default=False)
    can_discount     = models.BooleanField(default=True)
    can_view_reports = models.BooleanField(default=False)

    # ── Verification flags ─────────────────────────────────────────────────────
    # Set to True after the owner verifies via OTP (implemented later).
    # Profile page shows reminder banners when these are False.
    is_phone_verified = models.BooleanField(
        default=False,
        help_text="True after the owner confirms their phone number via OTP.",
    )
    is_email_verified = models.BooleanField(
        default=False,
        help_text="True after the owner confirms their email address.",
    )

    # ── Override AbstractUser PK conflict with BaseModel ──────────────────────
    id         = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ── REQUIRED_FIELDS: phone replaces email for createsuperuser ─────────────
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def save(self, *args, **kwargs):
        # Keep username in sync with phone so Django's auth backend works normally.
        if self.phone:
            self.username = self.phone
        # Coerce empty-string email to None so unique=True allows multiple null emails.
        # AbstractUser normalises email=None → "" which violates the unique constraint.
        if not self.email:
            self.email = None
        # Random avatar hue if not set
        if not self.avatar_hue or self.avatar_hue == 260:
            self.avatar_hue = random.randint(0, 359)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.phone

    @property
    def full_name(self):
        return self.get_full_name() or self.phone

    @property
    def initials(self):
        parts = self.get_full_name().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return (self.phone[:2]).upper()

    @property
    def get_organisation(self):
        """
        Returns the organisation this user belongs to.
        Owners have a direct FK; staff derive it from their store.
        """
        if self.organisation_id:
            return self.organisation
        if self.store_id:
            return self.store.organisation
        return None

    @property
    def is_owner(self):
        return self.role in (self.ROLE_OWNER, self.ROLE_ADMIN)

    @property
    def is_system_admin(self):
        return self.role == self.ROLE_ADMIN

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["first_name", "last_name"]


# ── AI Credit Usage ────────────────────────────────────────────────────────────

class AICredit(BaseModel):
    """
    Tracks monthly AI credit consumption per organisation.

    In the UI (sidenav footer):
      "AI CREDITS · MAY   2,418 / 5,000"
    """

    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="ai_credits",
    )

    year  = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()

    used      = models.PositiveIntegerField(default=0)
    allocated = models.PositiveIntegerField(default=5000)

    def __str__(self):
        return f"{self.organisation.name} — {self.year}/{self.month:02d} ({self.used}/{self.allocated})"

    @property
    def remaining(self):
        return max(0, self.allocated - self.used)

    @property
    def percentage_used(self):
        if self.allocated == 0:
            return 100
        return round(self.used / self.allocated * 100, 1)

    @classmethod
    def get_or_create_current(cls, organisation):
        now = timezone.now()
        obj, _ = cls.objects.get_or_create(
            organisation=organisation,
            year=now.year,
            month=now.month,
            defaults={"allocated": organisation.ai_credits_monthly},
        )
        return obj

    class Meta:
        verbose_name = "AI Credit"
        verbose_name_plural = "AI Credits"
        ordering = ["-year", "-month"]
        unique_together = [("organisation", "year", "month")]
