"""
apps/suppliers/services.py

Business logic for the suppliers app.

Functions:
  get_supplier_stats(store)              → KPI summary for the list page header
  get_outstanding_balance(supplier)      → TZS amount owed to one supplier
  mark_delivery_paid(delivery, user)     → mark a delivery as paid + record payment
"""

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (
    STATUS_ACTIVE,
    Supplier,
    SupplierDelivery,
    SupplierPayment,
)


def get_supplier_stats(store) -> dict:
    """
    Aggregate KPI stats for the suppliers list page header strip.

    Returns:
      {
        "total_suppliers":    int,
        "active_count":       int,
        "pending_invoices":   int,   # unpaid deliveries across all suppliers
        "total_outstanding":  int,   # TZS owed across all active suppliers
      }
    """
    suppliers = Supplier.objects.filter(store=store)

    total     = suppliers.count()
    active    = suppliers.filter(status=STATUS_ACTIVE).count()

    pending_invoices = SupplierDelivery.objects.filter(
        store=store,
        is_paid=False,
    ).count()

    total_invoiced = (
        SupplierDelivery.objects
        .filter(store=store)
        .aggregate(t=Sum("total_value"))["t"] or 0
    )
    total_paid = (
        SupplierPayment.objects
        .filter(store=store)
        .aggregate(t=Sum("amount"))["t"] or 0
    )
    total_outstanding = max(0, total_invoiced - total_paid)

    return {
        "total_suppliers":   total,
        "active_count":      active,
        "pending_invoices":  pending_invoices,
        "total_outstanding": total_outstanding,
    }


def get_outstanding_balance(supplier) -> int:
    """
    Compute the current outstanding balance for a single supplier.

    = sum(deliveries.total_value) - sum(payments.amount)

    Always returns >= 0. If somehow payments exceed invoices (data error),
    returns 0 rather than a negative number.
    """
    invoiced = supplier.deliveries.aggregate(t=Sum("total_value"))["t"] or 0
    paid     = supplier.payments.aggregate(t=Sum("amount"))["t"] or 0
    return max(0, invoiced - paid)


def mark_delivery_paid(delivery: SupplierDelivery, user, amount: int = None,
                       method: str = "cash", reference: str = "") -> SupplierPayment:
    """
    Mark a delivery as fully paid and create a SupplierPayment record.

    If `amount` is not provided, defaults to the full delivery value.
    Does NOT enforce that amount == delivery.total_value — partial payments
    are allowed (the caller decides the amount).

    Returns the created SupplierPayment.
    """
    if amount is None:
        amount = delivery.total_value

    payment = SupplierPayment.objects.create(
        supplier=delivery.supplier,
        store=delivery.store,
        organisation=delivery.organisation,
        delivery=delivery,
        amount=amount,
        payment_date=timezone.now().date(),
        payment_method=method,
        reference=reference,
        recorded_by=user,
    )

    # Only mark the delivery fully paid if the full amount was paid
    if amount >= delivery.total_value:
        delivery.is_paid = True
        delivery.save(update_fields=["is_paid", "updated_at"])

    return payment
