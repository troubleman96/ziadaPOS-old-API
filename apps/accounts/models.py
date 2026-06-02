"""
apps/accounts/models.py

Data models for user accounts, organisations, and stores.

Referenced UI pages:
  - Sidenav: shows store switcher ("Duka Kuu · Kariakoo · 3 stores")
  - Sidenav footer: shows logged-in user ("Hamisi Mwakapaga · Owner · admin")
  - Dashboard: "Good afternoon, Hamisi" personalisation
  - AI credits: "2,418 / 5,000" shown in sidenav footer

Model hierarchy:
  Organisation  (the business/company)
    └── Store   (physical locations)
         └── User (staff member, assigned to one store)

Key design decisions:
  - Custom User model (AbstractUser) — allows adding role, store FK, etc.
  - Role-based access: admin > manager > cashier
  - AI credits tracked per organisation per month
  - Store has its own tax ID (TIN) for receipts
"""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


# ── Organisation ──────────────────────────────────────────────────────────────

class Organisation(BaseModel):
    """
    The top-level entity — a business that owns one or more stores.

    In the UI: "Duka Kuu" is the organisation. It shows in the sidenav
    store switcher header.

    One Organisation can have multiple Stores (multi-branch support).
    """

    # Business trading name shown in the sidenav
    name = models.CharField(
        max_length=200,
        help_text="Trading name of the organisation, e.g. 'Duka Kuu'.",
    )

    # Legal/registered name (may differ from trading name)
    legal_name = models.CharField(
        max_length=300,
        blank=True,
        help_text="Full legal registered name.",
    )

    # Tanzania Revenue Authority (TRA) Tax Identification Number
    # Shown on receipts: "Tin: 109-882-461"
    tin = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="TIN",
        help_text="Tanzania TRA Tax Identification Number (printed on receipts).",
    )

    # Country / locale — defaults to Tanzania
    country = models.CharField(
        max_length=2,
        default="TZ",
        help_text="ISO 3166-1 alpha-2 country code.",
    )

    # Currency — all monetary values stored as integers (TZS = no sub-units)
    currency = models.CharField(
        max_length=3,
        default="TZS",
        help_text="ISO 4217 currency code.",
    )

    # Monthly AI credit allocation (shown in sidenav footer)
    ai_credits_monthly = models.PositiveIntegerField(
        default=5000,
        help_text="Total AI credits allocated per month (e.g. 5000).",
    )

    # Plan tier — controls feature access
    PLAN_FREE = "free"
    PLAN_PRO = "pro"
    PLAN_ENTERPRISE = "enterprise"
    PLAN_CHOICES = [
        (PLAN_FREE, "Free"),
        (PLAN_PRO, "Pro"),
        (PLAN_ENTERPRISE, "Enterprise"),
    ]
    plan = models.CharField(
        max_length=20,
        choices=PLAN_CHOICES,
        default=PLAN_FREE,
        help_text="Subscription plan tier.",
    )

    # When the trial ends (shown in POS trial banner)
    trial_ends_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Trial expiry datetime (null = not on trial).",
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Organisation"
        verbose_name_plural = "Organisations"
        ordering = ["name"]


# ── Store ─────────────────────────────────────────────────────────────────────

class Store(BaseModel):
    """
    A physical store location belonging to an Organisation.

    In the UI:
      - Sidenav: "Kariakoo · 3 stores" (the "3" means 3 Store records)
      - Dashboard: "Duka Kuu — Kariakoo" in page title
      - Receipts: "DUKA KUU — KARIAKOO" printed at top
      - Transactions: "store: 'Duka Kuu — Kariakoo'" field
    """

    # Parent organisation
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="stores",
        help_text="Organisation this store belongs to.",
    )

    # Store display name (shown in sidenav and receipts)
    name = models.CharField(
        max_length=200,
        help_text="Store name shown in the UI, e.g. 'Duka Kuu — Kariakoo'.",
    )

    # Short code used in transaction IDs (e.g. "KRC" → TXN-KRC-2043)
    code = models.CharField(
        max_length=10,
        blank=True,
        help_text="Short store code for transaction IDs.",
    )

    # Physical address
    address = models.TextField(
        blank=True,
        help_text="Full physical address of the store.",
    )

    # Neighbourhood / area (shown in sidenav: "Kariakoo")
    area = models.CharField(
        max_length=100,
        blank=True,
        help_text="Area / neighbourhood, e.g. 'Kariakoo'.",
    )

    # Tanzania phone number
    phone = models.CharField(
        max_length=30,
        blank=True,
        help_text="Store contact phone number.",
    )

    # Number of tills/registers (shown in POS: "Till #2")
    till_count = models.PositiveSmallIntegerField(
        default=1,
        help_text="Number of POS tills/registers in this store.",
    )

    # Contact email for this location
    email = models.EmailField(
        blank=True,
        help_text="Store email address, e.g. 'kariakoo@dukakuu.co.tz'.",
    )

    # Trading hours shown in the stores UI
    open_hours = models.CharField(
        max_length=50,
        blank=True,
        default="7:00 AM – 9:00 PM",
        help_text="Opening hours label shown in the UI, e.g. '7:00 AM – 9:00 PM'.",
    )

    # UI colour for store avatar / sparkline
    color = models.CharField(
        max_length=20,
        blank=True,
        default="#6366f1",
        help_text="Hex colour used for store avatar and sparkline in the UI.",
    )

    # Operational status — distinct from is_active (which means the store exists in the org)
    STATUS_OPEN   = "open"
    STATUS_CLOSED = "closed"
    STATUS_PAUSED = "paused"
    STATUS_CHOICES = [
        (STATUS_OPEN,   "Open"),    # currently trading
        (STATUS_CLOSED, "Closed"),  # after hours / temporarily closed
        (STATUS_PAUSED, "Paused"),  # deliberately paused (no POS activity)
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
        help_text="Operational status shown in the stores UI.",
    )

    # Whether the store is currently active/open
    is_active = models.BooleanField(
        default=True,
        help_text="Active stores appear in the store switcher.",
    )

    def __str__(self):
        return f"{self.organisation.name} — {self.name}"

    @property
    def display_name(self):
        """Full display name as shown in UI, e.g. 'Duka Kuu — Kariakoo'."""
        return f"{self.organisation.name} — {self.name}"

    class Meta:
        verbose_name = "Store"
        verbose_name_plural = "Stores"
        ordering = ["organisation__name", "name"]
        # Store names must be unique within an organisation
        unique_together = [("organisation", "name")]


# ── User (custom auth model) ──────────────────────────────────────────────────

class User(AbstractUser, BaseModel):
    """
    Custom User model — extends Django's AbstractUser.

    WHY custom? AbstractUser gives us username/password/email for free.
    We add: role, store assignment, phone, and avatar colour.

    In the UI (sidenav footer):
      - "Hamisi Mwakapaga" → full_name via first_name + last_name
      - "Owner · admin"    → role field
      - Avatar "HM"        → initials from name

    IMPORTANT: AUTH_USER_MODEL = 'accounts.User' in settings.py
    """

    # Role determines API permissions (see apps/core/permissions.py)
    ROLE_ADMIN = "admin"
    ROLE_MANAGER = "manager"
    ROLE_CASHIER = "cashier"
    ROLE_CHOICES = [
        (ROLE_ADMIN,   "Admin (Owner)"),   # Full access
        (ROLE_MANAGER, "Manager"),          # Store-level management
        (ROLE_CASHIER, "Cashier"),          # POS only
    ]
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_CASHIER,
        help_text="User role determines what actions they can perform.",
    )

    # Primary store assignment — users are scoped to one store
    # (multi-store access managed via org-level admin role)
    store = models.ForeignKey(
        Store,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staff",
        help_text="Primary store this user works at.",
    )

    # Phone number for WhatsApp / SMS contact
    phone = models.CharField(
        max_length=30,
        blank=True,
        help_text="User phone number (+255 7XX XXX XXX).",
    )

    # Hue value (0–360) for procedural avatar colour generation
    # (same pattern as credit customers in the UI)
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
        help_text="Assigned shift for this staff member.",
    )

    # ── Employment status (3-state, distinct from is_active login flag) ────────
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
        help_text="Employment status shown on the Staff page. "
                  "Distinct from is_active which controls login access.",
    )

    # ── POS access PIN ─────────────────────────────────────────────────────────
    pin = models.CharField(
        max_length=4,
        blank=True,
        help_text="4-digit POS access PIN (stored as plain text — not a security credential).",
    )

    # ── Per-staff permissions (override role defaults) ─────────────────────────
    can_refund = models.BooleanField(
        default=False,
        help_text="Allow this staff member to issue refunds at the POS.",
    )
    can_discount = models.BooleanField(
        default=True,
        help_text="Allow this staff member to apply discounts at the POS.",
    )
    can_view_reports = models.BooleanField(
        default=False,
        help_text="Allow this staff member to access Analytics and Reports.",
    )

    # Override AbstractUser's UUID field conflict:
    # AbstractUser uses id (int) by default — our BaseModel adds UUID id.
    # We resolve this by NOT using BaseModel's id directly;
    # instead we let AbstractUser handle the PK and just add our timestamps.

    # Remove the `id` UUID from BaseModel — AbstractUser handles PK
    # We still want created_at / updated_at but NOT a second `id` field.
    # Solution: override the `id` field to be an AutoField (Django default)
    # so AbstractUser's id wins and we keep the timestamps.
    id = models.AutoField(primary_key=True)  # Override BaseModel's UUID id

    # Keep BaseModel timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def full_name(self):
        """Full name: 'Hamisi Mwakapaga'."""
        return self.get_full_name() or self.username

    @property
    def initials(self):
        """Two-letter initials from full name, e.g. 'HM'."""
        parts = self.get_full_name().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return self.username[:2].upper()

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

    A new record is created each month. Usage is incremented with each
    AI API call in apps/ai/services.py.
    """

    # Which organisation this usage belongs to
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="ai_credits",
        help_text="Organisation consuming the AI credits.",
    )

    # Year and month of this usage period (e.g. 2026, 5 for May 2026)
    year = models.PositiveSmallIntegerField(
        help_text="Year of this usage period.",
    )
    month = models.PositiveSmallIntegerField(
        help_text="Month (1–12) of this usage period.",
    )

    # Credits consumed this month (starts at 0, incremented by AI service)
    used = models.PositiveIntegerField(
        default=0,
        help_text="AI credits consumed this month.",
    )

    # Credits allocated for this month (copied from org at period start)
    allocated = models.PositiveIntegerField(
        default=5000,
        help_text="Total AI credits available this month.",
    )

    def __str__(self):
        return f"{self.organisation.name} — {self.year}/{self.month:02d} ({self.used}/{self.allocated})"

    @property
    def remaining(self):
        """How many credits are left this month."""
        return max(0, self.allocated - self.used)

    @property
    def percentage_used(self):
        """Percentage consumed (0–100)."""
        if self.allocated == 0:
            return 100
        return round(self.used / self.allocated * 100, 1)

    @classmethod
    def get_or_create_current(cls, organisation):
        """
        Get (or create) the AI credit record for the current month.
        Called by apps/ai/services.py before each AI request.
        """
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
        # One record per organisation per month
        unique_together = [("organisation", "year", "month")]
