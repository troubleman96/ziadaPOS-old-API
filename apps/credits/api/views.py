"""
apps/credits/api/views.py

API views for the Credits ("madeni") app.

Referenced UI pages:
  /credits          → CreditsDashboardView (KPI strip, aging, customer list)
  /credits/[id]     → CustomerCreditProfileView (tabs, payments, messages, notes)

Endpoints:
  GET  /api/v1/credits/                           → dashboard: KPI + aging + customer list
  GET  /api/v1/credits/customers/{id}/            → full customer credit profile
  POST /api/v1/credits/customers/{id}/record-payment/  → record a payment
  POST /api/v1/credits/customers/{id}/send-reminder/   → log a message/reminder
  POST /api/v1/credits/customers/{id}/add-note/        → add internal note
  POST /api/v1/credits/tabs/{id}/write-off/            → write off a tab

Payment flow:
  1. POST record-payment with amount/method
  2. _apply_payment() distributes amount across open tabs (oldest first)
  3. Each affected tab.amount_paid is updated
  4. Tab status updated (open → partially_paid → settled)
  5. Customer.open_credit cache is recalculated
  6. CreditPayment record is created
"""

import logging
from datetime import timedelta

from django.db import transaction as db_transaction
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsStoreCashier, IsStoreManager
from apps.core.response import created_response, error_response, success_response
from apps.customers.models import Customer

from ..models import CreditMessage, CreditNote, CreditPayment, CreditTab
from .serializers import (
    AddCreditNoteSerializer,
    CreditCustomerRowSerializer,
    CreditMessageSerializer,
    CreditNoteSerializer,
    CreditPaymentSerializer,
    CreditTabSerializer,
    RecordPaymentSerializer,
    SendReminderSerializer,
)

logger = logging.getLogger(__name__)


def _get_customer_or_404(customer_id, store):
    """
    Helper: get Customer by id scoped to store, or return None.
    Returns (customer, error_response) tuple — caller checks for error.
    """
    try:
        return Customer.objects.get(id=customer_id, store=store), None
    except Customer.DoesNotExist:
        return None, error_response(f"Customer {customer_id} not found in this store.", status=404)


def _compute_credit_status(customer):
    """
    Determine the credit status and days label for a customer.

    Returns dict:
      {
        'status':   'overdue' | 'due-soon' | 'current',
        'due_days': int  (positive = days until due, negative = days overdue)
      }

    Logic:
      - If any tab is overdue → status='overdue', due_days = most overdue count (negative)
      - If any tab due within 7 days → status='due-soon', due_days = min days remaining
      - Otherwise → status='current', due_days = days until nearest due date
    """
    today = timezone.now().date()
    open_tabs = CreditTab.objects.filter(
        customer=customer,
        status__in=[CreditTab.STATUS_OPEN, CreditTab.STATUS_PARTIAL],
        due_date__isnull=False,
    ).order_by("due_date")

    if not open_tabs.exists():
        return {"status": "current", "due_days": 999}

    # Check for overdue
    overdue_tabs = open_tabs.filter(due_date__lt=today)
    if overdue_tabs.exists():
        most_overdue = overdue_tabs.order_by("due_date").first()
        days = (today - most_overdue.due_date).days
        return {"status": "overdue", "due_days": -days}

    # Check for due soon (within 7 days)
    soon_tabs = open_tabs.filter(due_date__lte=today + timedelta(days=7))
    if soon_tabs.exists():
        nearest = soon_tabs.first()
        days = (nearest.due_date - today).days
        return {"status": "due-soon", "due_days": days}

    # Current — return days until next due
    nearest = open_tabs.first()
    days = (nearest.due_date - today).days
    return {"status": "current", "due_days": days}


# ── Credits Dashboard ─────────────────────────────────────────────────────────

class CreditsDashboardView(APIView):
    """
    GET /api/v1/credits/

    Powers the /credits page. Returns:
      1. KPI strip:  total_outstanding, overdue, due_soon, recovered_this_month
      2. Aging buckets: current/1-7d/8-30d/31-60d/60+d
      3. Customer list: each customer's balance, status, last tab, last payment

    Query params:
      ?status=overdue|due-soon|current   → filter customer list
      ?search=Fatuma                      → search by name/phone
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return full credits dashboard data."""
        store = request.user.store
        today = timezone.now().date()

        # ── All customers with open credit in this store ────────────────────
        customers_qs = Customer.objects.filter(
            store=store,
            is_active=True,
            open_credit__gt=0,
        )

        # Optional search filter
        search = request.query_params.get("search", "").strip()
        if search:
            customers_qs = customers_qs.filter(
                Q(name__icontains=search) | Q(phone__icontains=search)
            )

        customers = list(customers_qs)

        # ── Build customer rows (with computed status) ─────────────────────
        rows = []
        for cust in customers:
            status_info = _compute_credit_status(cust)

            # Last tab
            last_tab = CreditTab.objects.filter(
                customer=cust,
                status__in=[CreditTab.STATUS_OPEN, CreditTab.STATUS_PARTIAL],
            ).order_by("-created_at").first()

            # Last payment
            last_pay = CreditPayment.objects.filter(
                customer=cust
            ).order_by("-created_at").first()

            rows.append({
                "id":              cust.id,
                "name":            cust.name,
                "phone":           cust.phone,
                "avatar_hue":      cust.avatar_hue,
                "initials":        cust.initials,
                "segment":         cust.segment,
                "balance":         cust.open_credit,
                "status":          status_info["status"],
                "due_days":        status_info["due_days"],
                "last_tab_date":   last_tab.created_at.date() if last_tab else None,
                "last_pay_date":   last_pay.created_at.date() if last_pay else None,
                "last_pay_amount": last_pay.amount if last_pay else None,
            })

        # Apply status filter after computing (cheaper than complex DB query)
        status_filter = request.query_params.get("status")
        if status_filter and status_filter != "all":
            rows = [r for r in rows if r["status"] == status_filter]

        # Sort: most overdue first (most negative due_days first)
        rows.sort(key=lambda r: r["due_days"])

        # ── KPI strip ──────────────────────────────────────────────────────
        total_outstanding = sum(r["balance"] for r in rows) if rows else 0
        overdue_total   = sum(r["balance"] for r in rows if r["status"] == "overdue")
        due_soon_total  = sum(r["balance"] for r in rows if r["status"] == "due-soon")

        # Recovered this month = payments made this month in this store
        month_start = today.replace(day=1)
        recovered = CreditPayment.objects.filter(
            store=store,
            created_at__date__gte=month_start,
        ).aggregate(s=Sum("amount"))["s"] or 0

        # ── Aging buckets ──────────────────────────────────────────────────
        aging = _compute_aging_buckets(store, today)

        data = {
            "kpis": {
                "total_outstanding": total_outstanding,
                "overdue":           overdue_total,
                "due_soon":          due_soon_total,
                "recovered_month":   recovered,
                "customer_count":    len(rows),
            },
            "aging_buckets": aging,
            "customers": rows,  # Already serialised as plain dicts
        }
        return success_response(data=data, message="Credits dashboard.")


def _compute_aging_buckets(store, today):
    """
    Compute aging bucket totals for CreditTabs in a store.

    Buckets (based on how many days overdue a tab is):
      Current (0d)   — tab not yet due or due today
      1–7 days       — 1 to 7 days overdue
      8–30 days      — 8 to 30 days overdue
      31–60 days     — 31 to 60 days overdue
      60+ days       — more than 60 days overdue

    Returns: list of bucket dicts with label, range, amount.
    """
    open_tabs = CreditTab.objects.filter(
        store=store,
        status__in=[CreditTab.STATUS_OPEN, CreditTab.STATUS_PARTIAL],
    )

    buckets = [
        {"label": "Current",    "range": "0 days",  "amount": 0},
        {"label": "1–7 days",   "range": "1–7d",    "amount": 0},
        {"label": "8–30 days",  "range": "8–30d",   "amount": 0},
        {"label": "31–60 days", "range": "31–60d",  "amount": 0},
        {"label": "60+ days",   "range": "60+d",    "amount": 0},
    ]

    for tab in open_tabs:
        balance = tab.balance
        if balance == 0:
            continue

        if not tab.due_date or tab.due_date >= today:
            buckets[0]["amount"] += balance
        else:
            days_overdue = (today - tab.due_date).days
            if days_overdue <= 7:
                buckets[1]["amount"] += balance
            elif days_overdue <= 30:
                buckets[2]["amount"] += balance
            elif days_overdue <= 60:
                buckets[3]["amount"] += balance
            else:
                buckets[4]["amount"] += balance

    return buckets


# ── Customer Credit Profile ───────────────────────────────────────────────────

class CustomerCreditProfileView(APIView):
    """
    GET /api/v1/credits/customers/{id}/

    Returns the full credit profile for a specific customer:
      - Customer info
      - All open/partial credit tabs
      - Full payment history
      - Communication log (messages)
      - Internal notes
      - Aggregated totals
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, customer_id):
        """Return full credit profile."""
        customer, err = _get_customer_or_404(customer_id, request.user.store)
        if err:
            return err

        tabs     = CreditTab.objects.filter(customer=customer).select_related("transaction", "cashier")
        payments = CreditPayment.objects.filter(customer=customer).select_related("cashier")
        messages = CreditMessage.objects.filter(customer=customer).select_related("sent_by")
        notes    = CreditNote.objects.filter(customer=customer).select_related("by")

        total_owed   = tabs.aggregate(s=Sum("amount"))["s"] or 0
        total_paid   = payments.aggregate(s=Sum("amount"))["s"] or 0
        open_balance = max(0, total_owed - total_paid)

        data = {
            "customer":     _serialise_customer_minimal(customer),
            "tabs":         CreditTabSerializer(tabs, many=True).data,
            "payments":     CreditPaymentSerializer(payments, many=True).data,
            "messages":     CreditMessageSerializer(messages, many=True).data,
            "notes":        CreditNoteSerializer(notes, many=True).data,
            "total_owed":   total_owed,
            "total_paid":   total_paid,
            "open_balance": open_balance,
            "tab_count":    tabs.count(),
            "payment_count": payments.count(),
        }
        return success_response(data=data, message="Customer credit profile.")


def _serialise_customer_minimal(customer):
    """Return a minimal customer dict — avoids a full serializer import cycle."""
    return {
        "id":         str(customer.id),
        "name":       customer.name,
        "phone":      customer.phone,
        "avatar_hue": customer.avatar_hue,
        "initials":   customer.initials,
        "segment":    customer.segment,
        "open_credit": customer.open_credit,
    }


# ── Record Payment ────────────────────────────────────────────────────────────

class RecordPaymentView(APIView):
    """
    POST /api/v1/credits/customers/{id}/record-payment/

    Records a credit payment and applies it to open tabs.

    Processing:
      1. Validate amount, method, reference
      2. Create CreditPayment record
      3. Apply payment to open tabs (oldest first) until amount is exhausted
      4. Update Customer.open_credit cache
      5. Return updated customer balance
    """

    permission_classes = [IsAuthenticated, IsStoreCashier]

    @db_transaction.atomic
    def post(self, request, customer_id):
        """Process a credit payment."""
        customer, err = _get_customer_or_404(customer_id, request.user.store)
        if err:
            return err

        if customer.open_credit == 0:
            return error_response("This customer has no outstanding balance.", status=400)

        serializer = RecordPaymentSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        data   = serializer.validated_data
        amount = data["amount"]

        # Create the payment record
        payment = CreditPayment.objects.create(
            customer=customer,
            store=request.user.store,
            amount=amount,
            method=data["method"],
            reference=data.get("reference", ""),
            cashier=request.user,
            note=data.get("note", ""),
        )

        # Apply payment to open tabs (oldest first)
        _apply_payment_to_tabs(customer, amount)

        # Recalculate and cache the open_credit on Customer
        _refresh_customer_credit(customer)

        logger.info(
            "User %s recorded payment of TZS %s from customer %s (%s)",
            request.user.username, amount, customer.name, customer.id,
        )
        return created_response(
            data={
                "payment": CreditPaymentSerializer(payment).data,
                "open_credit": customer.open_credit,
            },
            message=f"Payment of TZS {amount:,} recorded.",
        )


def _apply_payment_to_tabs(customer, amount_to_apply):
    """
    Distribute a payment amount across open CreditTabs (oldest first).

    Modifies tab.amount_paid and tab.status in-place (DB updates).
    Stops when the payment amount is exhausted.
    """
    open_tabs = CreditTab.objects.filter(
        customer=customer,
        status__in=[CreditTab.STATUS_OPEN, CreditTab.STATUS_PARTIAL],
    ).order_by("created_at")  # Oldest tab first

    remaining = amount_to_apply

    for tab in open_tabs:
        if remaining <= 0:
            break

        tab_balance = tab.balance  # amount - amount_paid
        apply = min(remaining, tab_balance)

        tab.amount_paid += apply
        remaining -= apply

        # Update status based on how much has been paid
        if tab.amount_paid >= tab.amount:
            tab.status = CreditTab.STATUS_SETTLED
        else:
            tab.status = CreditTab.STATUS_PARTIAL

        tab.save(update_fields=["amount_paid", "status", "updated_at"])


def _refresh_customer_credit(customer):
    """
    Recalculate and update the Customer.open_credit cache.
    open_credit = sum(tab.balance for open/partial tabs)
    """
    result = CreditTab.objects.filter(
        customer=customer,
        status__in=[CreditTab.STATUS_OPEN, CreditTab.STATUS_PARTIAL],
    ).aggregate(
        total_amount=Sum("amount"),
        total_paid=Sum("amount_paid"),
    )

    total_amount = result["total_amount"] or 0
    total_paid   = result["total_paid"]   or 0
    customer.open_credit = max(0, total_amount - total_paid)
    customer.save(update_fields=["open_credit", "updated_at"])


# ── Send Reminder ─────────────────────────────────────────────────────────────

class SendReminderView(APIView):
    """
    POST /api/v1/credits/customers/{id}/send-reminder/

    Logs a communication (WhatsApp, call, SMS) for a customer's credit.
    Also used by the AI to store auto-generated reminder messages.

    Note: This endpoint logs the message; actual WhatsApp sending is
    handled by a separate WhatsApp Business API integration (future scope).
    For MVP, the message is stored and the frontend opens the WhatsApp deep link.
    """

    permission_classes = [IsAuthenticated, IsStoreCashier]

    def post(self, request, customer_id):
        """Log a message/reminder for a customer."""
        customer, err = _get_customer_or_404(customer_id, request.user.store)
        if err:
            return err

        serializer = SendReminderSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        data = serializer.validated_data
        who  = data.get("who") or (
            request.user.get_full_name() or request.user.username
        )

        message = CreditMessage.objects.create(
            customer=customer,
            store=request.user.store,
            kind=data["kind"],
            direction=data["direction"],
            body=data["body"],
            who=who,
            sent_by=request.user,
        )

        return created_response(
            data=CreditMessageSerializer(message).data,
            message="Message logged.",
        )


# ── Add Note ──────────────────────────────────────────────────────────────────

class AddCreditNoteView(APIView):
    """
    POST /api/v1/credits/customers/{id}/add-note/

    Adds an internal staff note to a customer's credit record.
    Only managers and cashiers can add notes.
    """

    permission_classes = [IsAuthenticated, IsStoreCashier]

    def post(self, request, customer_id):
        """Add an internal note."""
        customer, err = _get_customer_or_404(customer_id, request.user.store)
        if err:
            return err

        serializer = AddCreditNoteSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        note = CreditNote.objects.create(
            customer=customer,
            store=request.user.store,
            body=serializer.validated_data["body"],
            by=request.user,
        )
        return created_response(
            data=CreditNoteSerializer(note).data,
            message="Note added.",
        )


# ── Write Off Tab ─────────────────────────────────────────────────────────────

class WriteOffTabView(APIView):
    """
    POST /api/v1/credits/tabs/{id}/write-off/

    Writes off a credit tab — marks it as 'written_off' and removes the
    balance from the customer's open_credit cache.
    Only managers may write off tabs.

    Body: { "reason": "Customer deceased / untraceable" }
    """

    permission_classes = [IsAuthenticated, IsStoreManager]

    @db_transaction.atomic
    def post(self, request, tab_id):
        """Write off a credit tab."""
        try:
            tab = CreditTab.objects.select_related("customer").get(
                id=tab_id,
                store=request.user.store,
            )
        except CreditTab.DoesNotExist:
            return error_response("Credit tab not found.", status=404)

        if tab.status == CreditTab.STATUS_SETTLED:
            return error_response("Cannot write off a settled tab.", status=400)
        if tab.status == CreditTab.STATUS_WRITTEN_OFF:
            return error_response("Tab is already written off.", status=400)

        reason = request.data.get("reason", "").strip()
        tab.status = CreditTab.STATUS_WRITTEN_OFF
        tab.write_off_reason = reason
        tab.save(update_fields=["status", "write_off_reason", "updated_at"])

        # Refresh customer credit cache
        _refresh_customer_credit(tab.customer)

        logger.info(
            "User %s wrote off tab %s (customer: %s). Reason: %s",
            request.user.username, tab.id, tab.customer.name, reason,
        )
        return success_response(
            data=CreditTabSerializer(tab).data,
            message=f"Tab written off. Customer: {tab.customer.name}.",
        )
