"""
apps/staff/services.py

Business logic for the staff app.

Functions:
  get_staff_stats(user)        → performance stats for a single staff member
  get_store_kpis(store)        → KPI summary across all staff for a store
  get_staff_activity(user, date) → today's transaction activity entries
  annotate_queryset_with_stats(qs) → annotate User queryset with DB-level stats
"""

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone


def annotate_queryset_with_stats(queryset):
    """
    Annotate a User queryset with today's and all-time transaction performance.
    Uses a single SQL JOIN — no N+1.  Falls back gracefully if the transactions
    app is unavailable (e.g. first migration run).

    Adds these attributes to each User object:
      _sales_today, _txns_today, _total_sales, _avg_ticket, _txns_total
    """
    today = timezone.now().date()
    try:
        return queryset.annotate(
            _sales_today=Sum(
                "transactions__total",
                filter=Q(
                    transactions__created_at__date=today,
                    transactions__status="paid",
                ),
            ),
            _txns_today=Count(
                "transactions",
                filter=Q(transactions__created_at__date=today),
                distinct=True,
            ),
            _total_sales=Sum(
                "transactions__total",
                filter=Q(transactions__status="paid"),
            ),
            _avg_ticket=Avg(
                "transactions__total",
                filter=Q(transactions__status="paid"),
            ),
            _txns_total=Count("transactions", distinct=True),
        )
    except Exception:
        return queryset


def get_staff_stats(user) -> dict:
    """
    Compute performance stats for a single staff member via direct DB queries.
    Used for the detail view and the /stats/ action.

    Returns:
      {
        user_id, full_name, role,
        sales_today, total_sales, avg_ticket,
        txns_today, txns_total,
        sales_this_month, txns_this_month,
      }
    """
    today = timezone.now().date()
    month_start = today.replace(day=1)

    try:
        txn_qs = user.transactions.all()

        today_qs = txn_qs.filter(created_at__date=today)
        paid_qs  = txn_qs.filter(status="paid")
        month_qs = txn_qs.filter(created_at__date__gte=month_start, status="paid")

        sales_today      = today_qs.filter(status="paid").aggregate(t=Sum("total"))["t"] or 0
        txns_today       = today_qs.count()
        total_sales      = paid_qs.aggregate(t=Sum("total"))["t"] or 0
        avg_result       = paid_qs.aggregate(a=Avg("total"))["a"]
        avg_ticket       = round(avg_result or 0)
        txns_total       = txn_qs.count()
        sales_this_month = month_qs.aggregate(t=Sum("total"))["t"] or 0
        txns_this_month  = txn_qs.filter(created_at__date__gte=month_start).count()

    except Exception:
        sales_today = txns_today = total_sales = avg_ticket = txns_total = 0
        sales_this_month = txns_this_month = 0

    return {
        "user_id":          user.pk,
        "full_name":        user.full_name,
        "role":             user.role,
        "employment_status": user.employment_status,
        "shift":            user.shift,
        "sales_today":      sales_today,
        "txns_today":       txns_today,
        "total_sales":      total_sales,
        "avg_ticket":       avg_ticket,
        "txns_total":       txns_total,
        "sales_this_month": sales_this_month,
        "txns_this_month":  txns_this_month,
    }


def get_store_kpis(store) -> dict:
    """
    KPI summary for all staff at a store.
    Used by GET /api/v1/staff/kpis/

    Returns:
      {
        total_staff, active, on_leave, inactive,
        on_shift_today,
        sales_today, txns_today,
        sales_this_month,
      }
    """
    from apps.accounts.models import User

    qs    = User.objects.filter(store=store)
    today = timezone.now().date()
    month_start = today.replace(day=1)
    weekday = timezone.now().weekday()  # 0=Mon … 6=Sun

    total    = qs.count()
    active   = qs.filter(employment_status=User.EMPLOYMENT_ACTIVE).count()
    on_leave = qs.filter(employment_status=User.EMPLOYMENT_ON_LEAVE).count()
    inactive = qs.filter(employment_status=User.EMPLOYMENT_INACTIVE).count()

    # Staff counted as "on shift today" based on shift assignment and day-of-week
    if weekday < 5:  # Mon–Fri
        on_shift = qs.filter(
            employment_status=User.EMPLOYMENT_ACTIVE,
        ).exclude(shift=User.SHIFT_WEEKEND).count()
    else:  # Sat–Sun
        on_shift = qs.filter(
            employment_status=User.EMPLOYMENT_ACTIVE,
            shift__in=[User.SHIFT_WEEKEND, User.SHIFT_FULL_DAY],
        ).count()

    try:
        from apps.transactions.models import Transaction
        store_txns    = Transaction.objects.filter(cashier__store=store)
        sales_today   = store_txns.filter(created_at__date=today, status="paid").aggregate(t=Sum("total"))["t"] or 0
        txns_today    = store_txns.filter(created_at__date=today).count()
        sales_month   = store_txns.filter(created_at__date__gte=month_start, status="paid").aggregate(t=Sum("total"))["t"] or 0
    except Exception:
        sales_today = txns_today = sales_month = 0

    return {
        "total_staff":      total,
        "active":           active,
        "on_leave":         on_leave,
        "inactive":         inactive,
        "on_shift_today":   on_shift,
        "sales_today":      sales_today,
        "txns_today":       txns_today,
        "sales_this_month": sales_month,
    }


def get_staff_activity(user, date=None) -> list:
    """
    Retrieve transaction activity entries for a staff member on a given date.
    Defaults to today.

    Returns a list of dicts matching the UI's ActivityEntry shape:
      { id, time, type, amount?, items?, note? }
    """
    if date is None:
        date = timezone.now().date()

    try:
        txn_qs = user.transactions.filter(
            created_at__date=date
        ).select_related("store").prefetch_related("lines").order_by("created_at")

        entries = []
        for txn in txn_qs:
            entry = {
                "id":     str(txn.id),
                "time":   txn.created_at.strftime("%-I:%M %p"),
                "type":   "refund" if txn.status == "refunded" else "sale",
                "amount": txn.total,
                "items":  txn.lines.count(),
                "method": txn.payment_method,
                "txn_number": txn.txn_number,
                "status": txn.status,
            }
            entries.append(entry)
        return entries

    except Exception:
        return []
