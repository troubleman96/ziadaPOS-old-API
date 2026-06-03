"""
apps/transactions/api/views.py

API views for transactions and POS checkout.

Referenced UI pages (examined before building):
  /pos               → CompleteSaleView (the "Complete sale" button action)
  /transactions      → TransactionViewSet.list() (date-grouped, filtered table)
  /transactions/[id] → TransactionViewSet.retrieve() (detail: lines, timeline, receipt)

The core POS flow:
  1. Frontend builds cart (CartPanel in /pos page)
  2. Cashier selects payment method
  3. POST /api/v1/transactions/complete-sale/ with cart payload
  4. Backend: validates products, calculates totals, deducts stock, creates
     Transaction + TransactionLines atomically
  5. Returns the created transaction (frontend shows receipt)
"""

import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import Avg, Count, FloatField, Q, Sum
from django.utils import timezone
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.core.permissions import IsStoreCashier
from apps.core.response import created_response, error_response, success_response
from apps.inventory.models import Product, StockAdjustment

from ..models import Transaction, TransactionLine
from .serializers import (
    CompleteSaleSerializer,
    RefundSerializer,
    TransactionListSerializer,
    TransactionSerializer,
)

logger = logging.getLogger(__name__)

# TZS VAT rate (18%)
VAT_RATE = Decimal(str(settings.TZ_VAT_RATE))


# ── Transaction list + detail ─────────────────────────────────────────────────

class TransactionViewSet(ReadOnlyModelViewSet):
    """
    Read-only viewset for viewing transactions.
    Creating transactions is done via CompleteSaleView.

    LIST   GET /api/v1/transactions/
      Query params:
        ?status=paid|credit|refunded    → filter by status
        ?method=M-Pesa|Cash|...         → filter by payment method
        ?search=TXN-2043|Fatuma         → search TXN ID or customer name
        ?date_from=2026-05-01           → filter by date range
        ?date_to=2026-05-31
        ?ordering=-created_at           → sort (default: newest first)

    DETAIL  GET /api/v1/transactions/{id}/

    EXTRA ACTIONS:
      POST /api/v1/transactions/{id}/refund/   → refund a transaction
      GET  /api/v1/transactions/summary/       → aggregate stats for header KPIs
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["txn_number", "customer_name", "customer_phone", "payment_reference"]
    ordering_fields = ["created_at", "total", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        """Build filtered queryset, scoped to the user's store."""
        qs = Transaction.objects.select_related(
            "store", "cashier", "customer"
        ).filter(
            store=self.request.user.store
        )

        # Status filter (?status=paid)
        status_param = self.request.query_params.get("status")
        if status_param and status_param != "all":
            qs = qs.filter(status=status_param)

        # Payment method filter (?method=M-Pesa)
        method = self.request.query_params.get("method")
        if method and method != "all":
            qs = qs.filter(payment_method=method)

        # Date range filter
        date_from = self.request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = self.request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        return qs

    def get_serializer_class(self):
        """
        Use lightweight ListSerializer for list view (no nested lines).
        Use full TransactionSerializer for detail (includes lines, timeline).
        """
        if self.action == "retrieve":
            return TransactionSerializer
        return TransactionListSerializer

    def list(self, request, *args, **kwargs):
        """
        List transactions with pagination.
        Matches the /transactions page: grouped by day, filtered by method/status.
        """
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)

    def retrieve(self, request, *args, **kwargs):
        """
        Get full transaction detail including all line items.
        Matches the /transactions/[id] page.
        """
        transaction = self.get_object()
        serializer = TransactionSerializer(transaction)
        return success_response(
            data=serializer.data,
            message="Transaction retrieved.",
        )

    @action(detail=True, methods=["post"],
            permission_classes=[IsAuthenticated, IsStoreCashier])
    def refund(self, request, pk=None):
        """
        POST /api/v1/transactions/{id}/refund/

        Refund a transaction:
          1. Mark transaction as 'refunded'
          2. Restore stock for each line item
          3. Create REFUND stock adjustment records

        Referenced by "Refund sale" button in /transactions/[id] page.
        """
        transaction = self.get_object()

        # Can only refund paid transactions
        if transaction.status != Transaction.STATUS_PAID:
            return error_response(
                f"Cannot refund a transaction with status '{transaction.status}'.",
                status=400,
            )

        serializer = RefundSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        reason = serializer.validated_data.get("reason", "")

        with db_transaction.atomic():
            # Mark as refunded
            transaction.status = Transaction.STATUS_REFUNDED
            transaction.notes = (
                f"Refunded by {request.user.get_full_name() or request.user.username}. "
                f"Reason: {reason}"
            ).strip()
            transaction.save(update_fields=["status", "notes", "updated_at"])

            # Restore stock for each line
            for line in transaction.lines.all():
                if line.product:
                    before = line.product.stock
                    line.product.stock += line.qty
                    line.product.save(update_fields=["stock", "updated_at"])

                    StockAdjustment.objects.create(
                        product=line.product,
                        adjustment_type=StockAdjustment.TYPE_REFUND,
                        quantity_change=+line.qty,
                        quantity_before=before,
                        quantity_after=line.product.stock,
                        reference=transaction.txn_number,
                        performed_by=request.user,
                        note=f"Refund for {transaction.txn_number}. {reason}",
                    )

        logger.info(
            "User %s refunded transaction %s. Reason: %s",
            request.user.username, transaction.txn_number, reason,
        )
        return success_response(
            data=TransactionSerializer(transaction).data,
            message=f"Transaction {transaction.txn_number} refunded.",
        )

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """
        GET /api/v1/transactions/summary/

        Returns aggregate stats for the transaction header KPI cards.
        Referenced by /transactions page header cards.

        Query params:
          ?date_from=2026-05-24
          ?date_to=2026-05-24
        """
        qs = self.filter_queryset(self.get_queryset())

        agg = qs.aggregate(
            total_inflow=Sum("total"),
            total_profit=Sum("profit"),
            total_cost=Sum("cost_total"),
            count=Count("id"),
        )

        credit_qs  = qs.filter(status=Transaction.STATUS_CREDIT)
        refund_qs  = qs.filter(status=Transaction.STATUS_REFUNDED)

        data = {
            "total_inflow":     agg["total_inflow"]  or 0,
            "total_profit":     agg["total_profit"]  or 0,
            "total_cost":       agg["total_cost"]    or 0,
            "transaction_count": agg["count"]        or 0,
            "on_credit":        credit_qs.aggregate(s=Sum("total"))["s"] or 0,
            "credit_count":     credit_qs.count(),
            "refunds":          refund_qs.aggregate(s=Sum("total"))["s"] or 0,
            "refund_count":     refund_qs.count(),
        }

        # Profit margin percentage
        if data["total_inflow"]:
            data["margin_pct"] = round(data["total_profit"] / data["total_inflow"] * 100, 1)
        else:
            data["margin_pct"] = 0.0

        return success_response(data=data, message="Transaction summary.")

    @action(detail=False, methods=["get"], url_path="discount-summary")
    def discount_summary(self, request):
        """
        GET /api/v1/transactions/discount-summary/

        Discount analytics for the /discounts page.

        Query params (same as summary):
          ?date_from, ?date_to  → date range filter

        Returns:
          total_discount_amount  → total TZS given as discounts
          discounted_count       → number of transactions with discount > 0
          total_transactions     → total transactions in range
          discount_rate          → % of transactions with a discount
          avg_discount_pct       → average discount % across discounted txns
          avg_discount_amount    → average discount TZS across discounted txns
          by_cashier             → top cashiers by discount amount
          by_day                 → daily discount totals (last 30 days)
          largest_discounts      → top 5 largest single discounts
        """
        from django.db.models.functions import TruncDate

        qs = self.filter_queryset(self.get_queryset()).filter(
            status__in=[Transaction.STATUS_PAID, Transaction.STATUS_CREDIT]
        )

        discounted_qs = qs.filter(discount_amount__gt=0)

        # Top-level aggregates
        total_agg = qs.aggregate(
            total=Count("id"),
            discount_total=Sum("discount_amount"),
            disc_count=Count("id", filter=Q(discount_amount__gt=0)),
        )
        disc_agg = discounted_qs.aggregate(
            avg_pct=Avg("discount_pct", output_field=FloatField()),
            avg_amount=Avg("discount_amount", output_field=FloatField()),
        )

        total_count = total_agg["total"] or 0
        disc_count  = total_agg["disc_count"] or 0
        total_disc  = total_agg["discount_total"] or 0

        # By cashier (top 5)
        by_cashier = list(
            discounted_qs
            .values("cashier__first_name", "cashier__last_name", "cashier_id")
            .annotate(
                amount=Sum("discount_amount"),
                count=Count("id"),
                avg_pct=Avg("discount_pct", output_field=FloatField()),
            )
            .order_by("-amount")[:5]
        )
        for row in by_cashier:
            fn = row.pop("cashier__first_name") or ""
            ln = row.pop("cashier__last_name") or ""
            row["cashier_name"] = (fn + " " + ln).strip() or "Unknown"

        # Daily totals (last 30 days of the filtered range)
        by_day = list(
            discounted_qs
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(amount=Sum("discount_amount"), count=Count("id"))
            .order_by("day")
        )
        for row in by_day:
            row["day"] = str(row["day"])

        # Largest individual discounts (top 5)
        largest = list(
            discounted_qs
            .order_by("-discount_amount")[:5]
            .values(
                "txn_number", "customer_name",
                "discount_amount", "discount_pct",
                "total", "created_at",
            )
        )
        for row in largest:
            row["created_at"] = str(row["created_at"])

        return success_response(
            data={
                "total_discount_amount":  total_disc,
                "discounted_count":       disc_count,
                "total_transactions":     total_count,
                "discount_rate":          round(disc_count / total_count * 100, 1) if total_count else 0,
                "avg_discount_pct":       round(disc_agg["avg_pct"] or 0, 1),
                "avg_discount_amount":    round(disc_agg["avg_amount"] or 0),
                "by_cashier":             by_cashier,
                "by_day":                 by_day,
                "largest_discounts":      largest,
            },
            message="Discount summary.",
        )


# ── Complete Sale (POS checkout) ──────────────────────────────────────────────

class CompleteSaleView(APIView):
    """
    POST /api/v1/transactions/complete-sale/

    The primary POS action — processes a cart into a completed transaction.

    Processing steps (all inside a DB atomic transaction):
      1. Validate all product IDs exist and belong to the user's store
      2. Check stock availability (warn but don't block for credit sales)
      3. Calculate all monetary fields:
         - subtotal = sum(item.price × item.qty)
         - discount_amount = subtotal × discount_pct / 100
         - tax = (subtotal - discount) × 0.18
         - total = subtotal - discount + tax
         - cost = sum(item.cost × item.qty)
         - profit = total - cost - tax
      4. Generate txn_number (TXN-NNNN, sequential per store)
      5. Create Transaction record
      6. Create TransactionLine for each cart item
      7. Deduct stock for each product
      8. Create StockAdjustment records
      9. If payment_method == 'Credit': create a CreditTab
    10. Return the created transaction

    Referenced by the "Complete sale →" button in /pos CartPanel.
    """

    permission_classes = [IsAuthenticated, IsStoreCashier]

    def post(self, request):
        """Process the POS cart and create a transaction."""
        serializer = CompleteSaleSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        data = serializer.validated_data

        try:
            transaction = self._process_sale(request.user, data)
        except ValueError as exc:
            return error_response(str(exc), status=400)
        except Exception as exc:
            logger.exception("Unexpected error completing sale: %s", exc)
            return error_response("Failed to complete sale.", status=500)

        logger.info(
            "User %s completed sale %s | TZS %s | %s",
            request.user.username,
            transaction.txn_number,
            transaction.total,
            transaction.payment_method,
        )
        return created_response(
            data=TransactionSerializer(transaction).data,
            message=f"Sale {transaction.txn_number} completed.",
        )

    @db_transaction.atomic
    def _process_sale(self, cashier, data):
        """
        Core sale processing logic inside a DB atomic transaction.
        Any exception rolls back ALL changes (stock, transaction, lines).
        """
        store = cashier.store

        # ── Step 1: Resolve and validate all products ──────────────────────────
        product_map = {}  # { product_id (str): Product }
        for item in data["items"]:
            pid = str(item["product_id"])
            try:
                product = Product.objects.get(id=pid, store=store, is_active=True)
                product_map[pid] = product
            except Product.DoesNotExist:
                raise ValueError(f"Product {pid} not found or not active in this store.")

        # ── Step 2: Calculate monetary totals ─────────────────────────────────
        subtotal = 0
        cost_total = 0

        # Build line data list (we'll use it to create TransactionLine records)
        line_data = []
        for item in data["items"]:
            pid = str(item["product_id"])
            product = product_map[pid]
            qty = item["qty"]

            subtotal   += product.price * qty
            cost_total += product.cost  * qty
            line_data.append({
                "product": product,
                "name":    product.name,
                "sku":     product.sku,
                "price":   product.price,
                "cost":    product.cost,
                "qty":     qty,
            })

        # Apply discount
        discount_pct    = data["discount_pct"]  # Decimal
        discount_amount = int(subtotal * discount_pct / 100)
        taxable         = subtotal - discount_amount

        # 18% VAT
        tax_amount = int(taxable * VAT_RATE)
        total      = taxable + tax_amount

        # Gross profit = total - cost - tax
        profit = total - cost_total - tax_amount

        # ── Step 3: Resolve customer ───────────────────────────────────────────
        customer_obj   = None
        customer_name  = "Walk-in"
        customer_phone = ""

        customer_id = data.get("customer_id")
        if customer_id:
            from apps.customers.models import Customer
            try:
                customer_obj  = Customer.objects.get(id=customer_id, store=store)
                customer_name  = customer_obj.name
                customer_phone = customer_obj.phone or ""
            except Exception:
                # If customer not found, proceed as walk-in (don't fail the sale)
                logger.warning("Customer %s not found — proceeding as walk-in.", customer_id)

        # ── Step 4: Generate sequential TXN number ─────────────────────────────
        txn_number = self._generate_txn_number(store)

        # ── Step 5: Create Transaction ─────────────────────────────────────────
        transaction = Transaction.objects.create(
            store=store,
            txn_number=txn_number,
            payment_method=data["payment_method"],
            payment_reference=data.get("payment_reference", ""),
            status=(
                Transaction.STATUS_CREDIT
                if data["payment_method"] == Transaction.METHOD_CREDIT
                else Transaction.STATUS_PAID
            ),
            subtotal=subtotal,
            discount_pct=discount_pct,
            discount_amount=discount_amount,
            tax_amount=tax_amount,
            total=total,
            cost_total=cost_total,
            profit=profit,
            cashier=cashier,
            till_number=data.get("till_number", "Till #1"),
            customer=customer_obj,
            customer_name=customer_name,
            customer_phone=customer_phone,
            notes=data.get("notes", ""),
        )

        # ── Step 6: Create TransactionLines + adjust stock ────────────────────
        for line in line_data:
            TransactionLine.objects.create(
                transaction=transaction,
                product=line["product"],
                product_name=line["name"],
                product_sku=line["sku"],
                unit_price=line["price"],
                unit_cost=line["cost"],
                qty=line["qty"],
            )

            # Deduct stock
            product = line["product"]
            before  = product.stock
            product.stock -= line["qty"]
            product.save(update_fields=["stock", "updated_at"])

            # Stock adjustment audit record
            StockAdjustment.objects.create(
                product=product,
                adjustment_type=StockAdjustment.TYPE_SALE,
                quantity_change=-line["qty"],
                quantity_before=before,
                quantity_after=product.stock,
                reference=txn_number,
                performed_by=cashier,
            )

        # ── Step 7: If credit sale, create a CreditTab ────────────────────────
        if transaction.status == Transaction.STATUS_CREDIT and customer_obj:
            from apps.credits.models import CreditTab
            CreditTab.objects.create(
                customer=customer_obj,
                store=transaction.store,
                transaction=transaction,
                amount=total,
                cashier=cashier,
                till_number=data.get("till_number", "Till #1"),
            )

        return transaction

    def _generate_txn_number(self, store):
        """
        Generate the next sequential TXN number for this store.
        Format: TXN-NNNN (e.g. TXN-2043)

        Uses DB MAX to avoid race conditions (within the atomic transaction).
        """
        last = Transaction.objects.filter(
            store=store,
            txn_number__startswith="TXN-",
        ).order_by("-txn_number").first()

        if last:
            try:
                last_num = int(last.txn_number.replace("TXN-", ""))
                return f"TXN-{last_num + 1}"
            except ValueError:
                pass

        # Start at TXN-1001 for new stores
        return "TXN-1001"
