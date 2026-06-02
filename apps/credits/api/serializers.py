"""
apps/credits/api/serializers.py

Serializers for the credits ("madeni") app.

Covers:
  CreditTabSerializer       — full tab detail with computed balance
  CreditTabListSerializer   — lightweight tab for list views
  CreditPaymentSerializer   — read/write payment recording
  RecordPaymentSerializer   — input validator for POST /record-payment/
  CreditMessageSerializer   — communication log entry
  SendReminderSerializer    — input for sending a WhatsApp/call reminder
  CreditNoteSerializer      — internal note
  AddCreditNoteSerializer   — input for adding a new note

  CustomerCreditProfileSerializer — combines all of the above for /credits/[id]

Key design:
  - All write serializers are separate from read serializers to keep validation
    logic clean and independent of display logic.
  - amount_paid and balance on CreditTab are read-only — updated by the payment
    recording service, not directly by clients.
"""

from rest_framework import serializers

from apps.customers.api.serializers import CustomerMinimalSerializer

from ..models import CreditMessage, CreditNote, CreditPayment, CreditTab


# ── CreditTab ─────────────────────────────────────────────────────────────────

class CreditTabSerializer(serializers.ModelSerializer):
    """
    Full read serialiser for a CreditTab.
    Used in customer credit profile (/credits/[id]).
    """

    # Computed properties from the model
    balance      = serializers.IntegerField(read_only=True)
    is_overdue   = serializers.BooleanField(read_only=True)
    txn_number   = serializers.CharField(read_only=True)

    # Nested minimal customer info
    customer_info = CustomerMinimalSerializer(source="customer", read_only=True)

    class Meta:
        model = CreditTab
        fields = [
            "id", "customer", "customer_info",
            "transaction", "txn_number", "store",
            "amount", "amount_paid", "balance",
            "status", "due_date", "is_overdue",
            "cashier", "till_number",
            "write_off_reason",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "transaction", "store", "amount_paid", "balance",
            "is_overdue", "txn_number", "created_at", "updated_at",
        ]


class CreditTabListSerializer(serializers.ModelSerializer):
    """
    Lightweight read serialiser for CreditTab list views.
    Shows just enough for the /credits customer list rows.
    """

    balance    = serializers.IntegerField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    txn_number = serializers.CharField(read_only=True)

    class Meta:
        model = CreditTab
        fields = [
            "id", "customer", "txn_number",
            "amount", "amount_paid", "balance",
            "status", "due_date", "is_overdue",
            "created_at",
        ]


# ── CreditPayment ─────────────────────────────────────────────────────────────

class CreditPaymentSerializer(serializers.ModelSerializer):
    """Read serialiser for payment history display."""

    cashier_name = serializers.SerializerMethodField()

    class Meta:
        model = CreditPayment
        fields = [
            "id", "customer", "store",
            "amount", "method", "reference",
            "cashier", "cashier_name", "note",
            "created_at",
        ]
        read_only_fields = ["id", "customer", "store", "cashier", "created_at"]

    def get_cashier_name(self, obj):
        if obj.cashier:
            return obj.cashier.get_full_name() or obj.cashier.username
        return "Unknown"


class RecordPaymentSerializer(serializers.Serializer):
    """
    Input validator for POST /credits/customers/{id}/record-payment/

    The frontend "Record payment" drawer (on /credits page) sends:
      {
        "amount":     50000,
        "method":     "M-Pesa",
        "reference":  "QGT5K3AB",   (optional)
        "note":       "Partial"      (optional)
      }
    """

    amount = serializers.IntegerField(
        min_value=1,
        help_text="Payment amount in TZS.",
    )
    method = serializers.ChoiceField(
        choices=CreditPayment.METHOD_CHOICES,
        default=CreditPayment.METHOD_CASH,
        help_text="Payment method.",
    )
    reference = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
        help_text="M-Pesa code, bank ref, etc.",
    )
    note = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional staff note.",
    )


# ── CreditMessage ─────────────────────────────────────────────────────────────

class CreditMessageSerializer(serializers.ModelSerializer):
    """Read serialiser for communication log."""

    class Meta:
        model = CreditMessage
        fields = [
            "id", "customer", "store",
            "kind", "direction", "body", "who", "sent_by",
            "created_at",
        ]
        read_only_fields = ["id", "customer", "store", "sent_by", "created_at"]


class SendReminderSerializer(serializers.Serializer):
    """
    Input for POST /credits/customers/{id}/send-reminder/

    Allows staff to log a manual reminder or record an inbound message.
    AI-generated reminders are also stored via this path (sent_by=None, who='auto-reminder').

      {
        "kind":      "whatsapp",
        "direction": "out",
        "body":      "Habari Juma, deni lako...",
        "who":       "Hamisi M."      (optional — defaults to request user)
      }
    """

    kind = serializers.ChoiceField(
        choices=CreditMessage.KIND_CHOICES,
        default=CreditMessage.KIND_WHATSAPP,
    )
    direction = serializers.ChoiceField(
        choices=CreditMessage.DIRECTION_CHOICES,
        default=CreditMessage.DIRECTION_OUT,
    )
    body = serializers.CharField(
        max_length=2000,
        help_text="Message body or call summary.",
    )
    who = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
        help_text="Who sent/logged this — defaults to the authenticated user's name.",
    )


# ── CreditNote ────────────────────────────────────────────────────────────────

class CreditNoteSerializer(serializers.ModelSerializer):
    """Read serialiser for internal credit notes."""

    author_name = serializers.SerializerMethodField()

    class Meta:
        model = CreditNote
        fields = ["id", "customer", "body", "by", "author_name", "created_at"]
        read_only_fields = ["id", "customer", "by", "created_at"]

    def get_author_name(self, obj):
        if obj.by:
            return obj.by.get_full_name() or obj.by.username
        return "Unknown"


class AddCreditNoteSerializer(serializers.Serializer):
    """Input for POST /credits/customers/{id}/add-note/"""

    body = serializers.CharField(
        max_length=2000,
        help_text="Note body.",
    )


# ── Customer Credit Profile ───────────────────────────────────────────────────

class CustomerCreditProfileSerializer(serializers.Serializer):
    """
    Composite read serialiser for the full credit profile of a customer.

    Used by GET /credits/customers/{id}/ which powers the /credits/[id] page:
      - Customer identity
      - All their credit tabs
      - Payment history
      - Communication log
      - Internal notes
      - Computed balance and status

    This is a read-only composite — it does not validate writes.
    """

    from apps.customers.api.serializers import CustomerSerializer as _CustomerSer

    customer  = CustomerMinimalSerializer()
    tabs      = CreditTabSerializer(many=True)
    payments  = CreditPaymentSerializer(many=True)
    messages  = CreditMessageSerializer(many=True)
    notes     = CreditNoteSerializer(many=True)

    # Aggregated totals
    total_owed    = serializers.IntegerField()
    total_paid    = serializers.IntegerField()
    open_balance  = serializers.IntegerField()
    tab_count     = serializers.IntegerField()
    payment_count = serializers.IntegerField()


# ── Credits list summary ──────────────────────────────────────────────────────

class CreditCustomerRowSerializer(serializers.Serializer):
    """
    Serialiser for one row in the /credits customer list.
    Combines the Customer record with aggregated credit stats.

    Each row shows: name, phone, balance, status (overdue/due-soon/current),
    due_days, last tab date, last payment.
    """

    id           = serializers.UUIDField()
    name         = serializers.CharField()
    phone        = serializers.CharField()
    avatar_hue   = serializers.IntegerField()
    initials     = serializers.CharField()
    segment      = serializers.CharField()
    balance      = serializers.IntegerField()    # open_credit cached field
    status       = serializers.CharField()        # overdue / due-soon / current
    due_days     = serializers.IntegerField()     # days until due (negative = overdue)
    last_tab_date    = serializers.DateField(allow_null=True)
    last_pay_date    = serializers.DateField(allow_null=True)
    last_pay_amount  = serializers.IntegerField(allow_null=True)
