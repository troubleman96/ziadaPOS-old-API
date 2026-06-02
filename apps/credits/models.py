"""
apps/credits/models.py

Models for the credit ("madeni") management system.

Referenced UI pages examined before building:
  /credits         → CreditTab list, aging buckets, KPI strip, "Record payment" drawer
  /credits/[id]    → Full customer credit profile: tabs, payments, messages, notes

The credit lifecycle:
  1. Cashier selects "Credit" payment at POS → Transaction is created with status=credit
  2. CompleteSaleView._process_sale() creates a CreditTab linked to Transaction + Customer
  3. Tab appears in /credits list under the customer
  4. Customer pays → CreditPayment is recorded
  5. When total payments >= total tabs, tab status → 'settled'
  6. Staff can log reminders (WhatsApp/call) as CreditMessages
  7. Staff can add internal CreditNotes

Balance calculation:
  Customer.open_credit = sum(tab.amount for all open/partial tabs)
                       - sum(payment.amount for all payments)
  This is a cached field on Customer updated via signals.

Key design decisions:
  - CreditPayment is linked to Customer (not a specific tab) because payments
    often cover multiple tabs or partial amounts — just like real-world credit.
  - CreditMessage stores both outbound automated reminders and inbound customer replies.
  - CreditNote is internal staff-only notes, not customer-visible.
  - All amounts are TZS integers (no sub-units).
  - Tabs are NEVER deleted; they can be written off with a reason.
"""

from django.db import models

from apps.accounts.models import Store, User
from apps.core.models import BaseModel
from apps.customers.models import Customer


class CreditTab(BaseModel):
    """
    A single credit sale tab.

    Created automatically by CompleteSaleView when payment_method == 'Credit'.
    Each tab represents one transaction done on credit by a specific customer.

    Table: credits_credittab
    """

    # ── Status choices ────────────────────────────────────────────────────────
    STATUS_OPEN         = "open"
    STATUS_PARTIAL      = "partially_paid"
    STATUS_SETTLED      = "settled"
    STATUS_WRITTEN_OFF  = "written_off"

    STATUS_CHOICES = [
        (STATUS_OPEN,         "Open"),
        (STATUS_PARTIAL,      "Partially paid"),
        (STATUS_SETTLED,      "Settled"),
        (STATUS_WRITTEN_OFF,  "Written off"),
    ]

    # ── Relationships ─────────────────────────────────────────────────────────

    # The customer who owes this debt
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,     # Don't delete tabs when customer is soft-deleted
        related_name="credit_tabs",
        help_text="Customer who bought on credit.",
    )

    # The transaction that triggered this tab.
    # Nullable because a tab could theoretically be created manually by a manager.
    transaction = models.OneToOneField(
        "transactions.Transaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_tab",
        help_text="POS transaction that created this credit tab.",
    )

    # The store (denormalized from customer.store for fast filtering)
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="credit_tabs",
        help_text="Store where the credit was issued.",
    )

    # ── Financial fields ──────────────────────────────────────────────────────

    # The total amount owed from this sale (TZS integer)
    amount = models.PositiveIntegerField(
        help_text="Total amount of the credit sale (TZS).",
    )

    # Amount paid so far against this specific tab (TZS integer, cached)
    amount_paid = models.PositiveIntegerField(
        default=0,
        help_text="Total amount paid towards this tab so far (TZS, cached).",
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
        help_text="Current status of this credit tab.",
    )

    # Date payment is expected (default: 30 days after issue)
    due_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date by which payment is expected.",
    )

    # If written off, why?
    write_off_reason = models.TextField(
        blank=True,
        default="",
        help_text="Reason for writing off this tab (if applicable).",
    )

    # ── Staff ─────────────────────────────────────────────────────────────────

    # The cashier who issued the credit
    cashier = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_tabs_issued",
        help_text="Cashier who created this credit tab.",
    )

    till_number = models.CharField(
        max_length=20,
        blank=True,
        default="Till #1",
        help_text="Register/till where credit was issued.",
    )

    class Meta:
        """Meta options for CreditTab."""
        db_table = "credits_credittab"
        ordering = ["-created_at"]
        verbose_name = "Credit Tab"
        verbose_name_plural = "Credit Tabs"
        indexes = [
            models.Index(fields=["customer", "status"], name="idx_credittab_cust_status"),
            models.Index(fields=["store", "status"],    name="idx_credittab_store_status"),
            models.Index(fields=["due_date"],            name="idx_credittab_due_date"),
        ]

    def __str__(self):
        return f"CreditTab {self.id} — {self.customer.name} — TZS {self.amount:,} ({self.status})"

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def balance(self) -> int:
        """
        Outstanding balance on this specific tab.
        balance = amount - amount_paid
        """
        return max(0, self.amount - self.amount_paid)

    @property
    def is_overdue(self) -> bool:
        """True if tab has a due_date in the past and is not settled."""
        from django.utils import timezone
        if self.due_date and self.status in (self.STATUS_OPEN, self.STATUS_PARTIAL):
            return self.due_date < timezone.now().date()
        return False

    @property
    def txn_number(self) -> str:
        """Return the linked transaction number, or '—' if not linked."""
        if self.transaction:
            return self.transaction.txn_number
        return "—"


class CreditPayment(BaseModel):
    """
    A payment made by a customer towards their outstanding credit balance.

    Payments are linked to a Customer (not a specific tab) because real-world
    customers often make lump-sum payments that cover multiple tabs. The system
    distributes the payment across open tabs oldest-first.

    On creation:
      1. Finds all open/partial tabs for the customer (oldest first)
      2. Applies the payment amount against them in order
      3. Updates tab.amount_paid and tab.status
      4. Updates Customer.open_credit cache

    Table: credits_creditpayment
    """

    # ── Method choices ────────────────────────────────────────────────────────
    METHOD_CASH   = "Cash"
    METHOD_MPESA  = "M-Pesa"
    METHOD_BANK   = "Bank"
    METHOD_TIGOPESA = "Tigo Pesa"

    METHOD_CHOICES = [
        (METHOD_CASH,    "Cash"),
        (METHOD_MPESA,   "M-Pesa"),
        (METHOD_BANK,    "Bank transfer"),
        (METHOD_TIGOPESA, "Tigo Pesa"),
    ]

    # ── Relationships ─────────────────────────────────────────────────────────

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="credit_payments",
        help_text="Customer making this payment.",
    )

    # The store (for fast scoping in queries)
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="credit_payments",
        help_text="Store where the payment was recorded.",
    )

    # ── Financial ─────────────────────────────────────────────────────────────

    amount = models.PositiveIntegerField(
        help_text="Payment amount (TZS).",
    )

    method = models.CharField(
        max_length=20,
        choices=METHOD_CHOICES,
        default=METHOD_CASH,
        help_text="Payment method used.",
    )

    # Mobile money or bank reference number
    reference = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Payment reference (M-Pesa code, bank ref, etc.).",
    )

    # ── Staff ─────────────────────────────────────────────────────────────────

    cashier = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_payments_recorded",
        help_text="Staff member who recorded this payment.",
    )

    note = models.TextField(
        blank=True,
        default="",
        help_text="Optional note (e.g. 'Partial payment, rest next week').",
    )

    class Meta:
        """Meta options for CreditPayment."""
        db_table = "credits_creditpayment"
        ordering = ["-created_at"]
        verbose_name = "Credit Payment"
        verbose_name_plural = "Credit Payments"
        indexes = [
            models.Index(fields=["customer", "created_at"], name="idx_creditpay_cust_date"),
        ]

    def __str__(self):
        return f"Payment {self.id} — {self.customer.name} — TZS {self.amount:,} ({self.method})"


class CreditMessage(BaseModel):
    """
    A communication record related to credit follow-up.

    Covers:
      - Outbound automated WhatsApp reminders (kind='whatsapp', direction='out')
      - Outbound manual WhatsApp messages from staff
      - Inbound customer replies (direction='in')
      - Phone call logs (kind='call', direction='out')
      - SMS notifications (kind='sms')

    The /credits/[id] page shows these as a timeline/thread.

    Table: credits_creditmessage
    """

    # ── Kind choices ──────────────────────────────────────────────────────────
    KIND_WHATSAPP = "whatsapp"
    KIND_CALL     = "call"
    KIND_SMS      = "sms"

    KIND_CHOICES = [
        (KIND_WHATSAPP, "WhatsApp"),
        (KIND_CALL,     "Phone call"),
        (KIND_SMS,      "SMS"),
    ]

    # ── Direction choices ─────────────────────────────────────────────────────
    DIRECTION_IN  = "in"
    DIRECTION_OUT = "out"

    DIRECTION_CHOICES = [
        (DIRECTION_IN,  "Inbound (from customer)"),
        (DIRECTION_OUT, "Outbound (to customer)"),
    ]

    # ── Relationships ─────────────────────────────────────────────────────────

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="credit_messages",
        help_text="Customer involved in this communication.",
    )

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="credit_messages",
    )

    # ── Content ───────────────────────────────────────────────────────────────

    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        default=KIND_WHATSAPP,
        help_text="Communication channel.",
    )

    direction = models.CharField(
        max_length=5,
        choices=DIRECTION_CHOICES,
        default=DIRECTION_OUT,
        help_text="Whether this message was sent TO or received FROM the customer.",
    )

    # Message body / call summary
    body = models.TextField(
        help_text="Message text or call summary.",
    )

    # Who sent / logged this message.
    # 'auto-reminder' for system-generated, or the staff member's name.
    who = models.CharField(
        max_length=100,
        default="",
        help_text="Sender name, e.g. 'Hamisi M.' or 'auto-reminder'.",
    )

    # Optional FK to the actual user (null for automated messages)
    sent_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_messages_sent",
        help_text="Staff user who sent/logged this (null for auto-reminders).",
    )

    class Meta:
        """Meta options for CreditMessage."""
        db_table = "credits_creditmessage"
        ordering = ["-created_at"]
        verbose_name = "Credit Message"
        verbose_name_plural = "Credit Messages"

    def __str__(self):
        return f"{self.kind.title()} {self.direction} — {self.customer.name} — {self.created_at:%Y-%m-%d}"


class CreditNote(BaseModel):
    """
    Internal staff note on a customer's credit relationship.

    Notes are staff-only (not visible to the customer) and appear on the
    /credits/[id] page as a note thread.
    Use cases: 'Agreed to pay end of month', 'Do not extend credit — dodgy'.

    Table: credits_creditnote
    """

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="credit_notes",
        help_text="Customer this note is about.",
    )

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="credit_notes",
    )

    body = models.TextField(
        help_text="Note content.",
    )

    # The staff member who wrote this note
    by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_notes_written",
        help_text="Staff member who wrote this note.",
    )

    class Meta:
        """Meta options for CreditNote."""
        db_table = "credits_creditnote"
        ordering = ["-created_at"]
        verbose_name = "Credit Note"
        verbose_name_plural = "Credit Notes"

    def __str__(self):
        author = self.by.username if self.by else "unknown"
        return f"Note by {author} on {self.customer.name} ({self.created_at:%Y-%m-%d})"
