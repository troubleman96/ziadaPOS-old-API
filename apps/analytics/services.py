"""
apps/analytics/services.py

Business logic for analytics data aggregation.

These service functions are called by the API views and by the management
command / signals that rebuild DailySummary rows.

Key functions:
  rebuild_daily_summary(store, date)      — recompute one day's summary from raw txns
  get_revenue_trend(store, start, end)    — day-by-day revenue series for charts
  get_payment_mix(store, start, end)      — breakdown of revenue by payment method
  get_top_products(store, start, end)     — most sold products by revenue/qty
  get_kpi_summary(store, start, end)      — aggregate KPIs for the analytics header

  get_sales_breakdown(store, start, end)   — category revenue, DOW avg, hourly pattern
  get_product_performance(store, ...)      — full product table with margin + trend
  get_customer_analytics(store, start, end) — visits, segments, cohorts, top customers
  get_cashflow(store, start, end)          — daily cash in/out, expense breakdown
  get_dashboard_data(store)               — all dashboard widgets in one call
"""

from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count, Max, Min, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.db.models.functions import ExtractHour

from apps.transactions.models import Transaction, TransactionLine

from .models import DailySummary


# ── Daily Summary Rebuild ─────────────────────────────────────────────────────

def rebuild_daily_summary(store, target_date: date) -> DailySummary:
    """
    Recompute (or create) the DailySummary for a given store and date.

    This is idempotent: if called multiple times for the same day, it
    overwrites the existing row with fresh aggregated data.

    Called by:
      - Transaction post_save signal (for today)
      - Management command rebuild_daily_summaries (for backfills)

    Returns the DailySummary instance (created or updated).
    """
    # All transactions for this store and date
    qs = Transaction.objects.filter(
        store=store,
        created_at__date=target_date,
    )

    # Paid transactions (revenue-generating)
    paid_qs   = qs.filter(status=Transaction.STATUS_PAID)
    credit_qs = qs.filter(status=Transaction.STATUS_CREDIT)
    refund_qs = qs.filter(status=Transaction.STATUS_REFUNDED)

    # Revenue aggregates
    paid_agg = paid_qs.aggregate(
        revenue=Sum("total"),
        profit=Sum("profit"),
        cost=Sum("cost_total"),
        tax=Sum("tax_amount"),
        count=Count("id"),
    )
    credit_agg = credit_qs.aggregate(
        revenue=Sum("total"),
        count=Count("id"),
    )
    refund_agg = refund_qs.aggregate(
        total=Sum("total"),
    )

    # Payment method breakdown (paid transactions only)
    method_sums = {}
    for method_total in (
        paid_qs.values("payment_method")
               .annotate(total=Sum("total"))
    ):
        method_sums[method_total["payment_method"]] = method_total["total"] or 0

    # Distinct registered customers
    customer_count = (
        qs.filter(customer__isnull=False)
          .values("customer")
          .distinct()
          .count()
    )

    # Upsert the DailySummary row
    summary, _ = DailySummary.objects.update_or_create(
        store=store,
        date=target_date,
        defaults={
            "transaction_count": (paid_agg["count"] or 0) + (credit_agg.get("count") or 0),
            "customer_count":    customer_count,
            "revenue":           paid_agg["revenue"]  or 0,
            "credit_revenue":    credit_agg["revenue"] or 0,
            "cost_total":        paid_agg["cost"]     or 0,
            "profit":            paid_agg["profit"]   or 0,
            "tax_collected":     paid_agg["tax"]      or 0,
            "refund_total":      refund_agg["total"]  or 0,
            "cash_revenue":      method_sums.get(Transaction.METHOD_CASH,   0),
            "mpesa_revenue":     method_sums.get(Transaction.METHOD_MPESA,  0),
            "tigo_revenue":      method_sums.get(Transaction.METHOD_TIGO,   0),
            "bank_revenue":      method_sums.get(Transaction.METHOD_BANK,   0),
            "credit_issued":     credit_agg["revenue"] or 0,
        },
    )
    return summary


# ── Revenue Trend ─────────────────────────────────────────────────────────────

def get_revenue_trend(store, start_date: date, end_date: date) -> list[dict]:
    """
    Return a day-by-day list of revenue values for charting.

    Result: [
      {"date": "2026-05-01", "revenue": 1200000, "profit": 264000, "transactions": 42},
      ...
    ]

    Fills in zero for days with no DailySummary (store was closed / no sales).
    Uses DailySummary rows for performance.
    """
    # Fetch all available summaries in the range
    summaries = {
        s.date: s
        for s in DailySummary.objects.filter(
            store=store,
            date__gte=start_date,
            date__lte=end_date,
        )
    }

    # Build a complete day-by-day series (including zero days)
    result = []
    current = start_date
    while current <= end_date:
        s = summaries.get(current)
        result.append({
            "date":         current.isoformat(),
            "label":        current.strftime("%-d %b"),    # "3 May"
            "revenue":      s.revenue + s.credit_revenue if s else 0,
            "profit":       s.profit                      if s else 0,
            "transactions": s.transaction_count            if s else 0,
        })
        current += timedelta(days=1)

    return result


# ── Payment Mix ───────────────────────────────────────────────────────────────

def get_payment_mix(store, start_date: date, end_date: date) -> list[dict]:
    """
    Return revenue breakdown by payment method as percentage slices.

    Result: [
      {"method": "M-Pesa",   "amount": 4800000, "pct": 48},
      {"method": "Cash",     "amount": 2800000, "pct": 28},
      ...
    ]

    Reads from DailySummary for speed.
    """
    agg = DailySummary.objects.filter(
        store=store,
        date__gte=start_date,
        date__lte=end_date,
    ).aggregate(
        cash=Sum("cash_revenue"),
        mpesa=Sum("mpesa_revenue"),
        tigo=Sum("tigo_revenue"),
        bank=Sum("bank_revenue"),
        credit=Sum("credit_issued"),
    )

    totals = {
        "Cash":      agg["cash"]   or 0,
        "M-Pesa":    agg["mpesa"]  or 0,
        "Tigo Pesa": agg["tigo"]   or 0,
        "Bank":      agg["bank"]   or 0,
        "Credit":    agg["credit"] or 0,
    }

    grand_total = sum(totals.values()) or 1  # Avoid division by zero

    return [
        {
            "method": method,
            "amount": amount,
            "pct":    round(amount / grand_total * 100, 1),
        }
        for method, amount in totals.items()
        if amount > 0  # Only include methods with actual sales
    ]


# ── KPI Aggregation ───────────────────────────────────────────────────────────

def get_kpi_summary(store, start_date: date, end_date: date) -> dict:
    """
    Aggregate KPIs for the analytics page header strip.

    Returns dict with:
      revenue, profit, margin_pct, transaction_count,
      customer_count, avg_ticket, refund_total, tax_collected

    Also calculates period-over-period delta by comparing to the
    equivalent prior period (same length, immediately before start_date).
    """
    # Current period
    period_days = (end_date - start_date).days + 1
    summaries = DailySummary.objects.filter(
        store=store,
        date__gte=start_date,
        date__lte=end_date,
    )

    agg = summaries.aggregate(
        revenue=Sum("revenue"),
        credit_rev=Sum("credit_revenue"),
        profit=Sum("profit"),
        cost=Sum("cost_total"),
        tax=Sum("tax_collected"),
        refunds=Sum("refund_total"),
        transactions=Sum("transaction_count"),
        customers=Sum("customer_count"),
    )

    total_revenue = (agg["revenue"] or 0) + (agg["credit_rev"] or 0)
    total_profit  = agg["profit"]       or 0
    transactions  = agg["transactions"] or 0

    # Prior period (same length, immediately preceding)
    prior_end   = start_date - timedelta(days=1)
    prior_start = prior_end - timedelta(days=period_days - 1)

    prior_agg = DailySummary.objects.filter(
        store=store,
        date__gte=prior_start,
        date__lte=prior_end,
    ).aggregate(
        revenue=Sum("revenue"),
        credit_rev=Sum("credit_revenue"),
        transactions=Sum("transaction_count"),
    )
    prior_revenue = (prior_agg["revenue"] or 0) + (prior_agg["credit_rev"] or 0)
    prior_txns    = prior_agg["transactions"] or 0

    def pct_delta(current, prior):
        """Calculate percentage change from prior to current."""
        if not prior:
            return None
        return round((current - prior) / prior * 100, 1)

    return {
        "revenue":           total_revenue,
        "profit":            total_profit,
        "margin_pct":        round(total_profit / total_revenue * 100, 1) if total_revenue else 0.0,
        "transaction_count": transactions,
        "customer_count":    agg["customers"] or 0,
        "avg_ticket":        total_revenue // transactions if transactions else 0,
        "tax_collected":     agg["tax"]     or 0,
        "refund_total":      agg["refunds"] or 0,
        # Period-over-period deltas
        "revenue_delta_pct":      pct_delta(total_revenue, prior_revenue),
        "transaction_delta_pct":  pct_delta(transactions, prior_txns),
    }


# ── Top Products ──────────────────────────────────────────────────────────────

def get_top_products(store, start_date: date, end_date: date, limit: int = 10) -> list[dict]:
    """
    Return the top `limit` products by total revenue in the given period.

    Reads directly from TransactionLine for accuracy (DailySummary doesn't
    have per-product breakdowns).

    Result: [
      {
        "product_id": "...", "product_name": "Unga wa Sembe 10kg",
        "product_sku": "UNGA-001",
        "qty_sold": 134, "revenue": 3819000,
        "cost": 2948000, "profit": 871000,
      },
      ...
    ]
    """
    lines = (
        TransactionLine.objects
        .filter(
            transaction__store=store,
            transaction__created_at__date__gte=start_date,
            transaction__created_at__date__lte=end_date,
            transaction__status__in=[Transaction.STATUS_PAID, Transaction.STATUS_CREDIT],
        )
        .values("product_id", "product_name", "product_sku")
        .annotate(
            qty_sold=Sum("qty"),
            revenue=Sum(
                models.ExpressionWrapper(
                    models.F("unit_price") * models.F("qty"),
                    output_field=models.IntegerField(),
                )
            ),
            cost=Sum(
                models.ExpressionWrapper(
                    models.F("unit_cost") * models.F("qty"),
                    output_field=models.IntegerField(),
                )
            ),
        )
        .order_by("-revenue")[:limit]
    )

    results = []
    for line in lines:
        rev  = line["revenue"]  or 0
        cost = line["cost"]     or 0
        results.append({
            "product_id":   str(line["product_id"]) if line["product_id"] else None,
            "product_name": line["product_name"],
            "product_sku":  line["product_sku"],
            "qty_sold":     line["qty_sold"] or 0,
            "revenue":      rev,
            "cost":         cost,
            "profit":       rev - cost,
        })

    return results


# ── Date Range Parser ─────────────────────────────────────────────────────────

def parse_date_range(query_params) -> tuple[date, date]:
    """
    Parse ?range=7d|30d|90d|ytd or ?date_from=...&date_to=... from request query params.

    Returns (start_date, end_date) as Python date objects.
    Default: last 30 days.
    """
    today = date.today()

    # Explicit date range takes priority
    date_from = query_params.get("date_from")
    date_to   = query_params.get("date_to")
    if date_from and date_to:
        try:
            return (
                date.fromisoformat(date_from),
                date.fromisoformat(date_to),
            )
        except ValueError:
            pass  # Fall through to range param

    # Named range shorthand
    range_param = query_params.get("range", "30d")

    if range_param == "7d":
        return today - timedelta(days=6), today
    if range_param == "90d":
        return today - timedelta(days=89), today
    if range_param == "ytd":
        return date(today.year, 1, 1), today

    # Default: 30d
    return today - timedelta(days=29), today


# ── Import for F/ExpressionWrapper ──────────────────────────────────────────
from django.db import models


# ── Sales Breakdown ───────────────────────────────────────────────────────────

def get_sales_breakdown(store, start_date: date, end_date: date) -> dict:
    """
    Return detailed sales breakdown for the /analytics/sales sub-page.

    Sections:
      category_breakdown — revenue by product category + trend vs prior period
      day_of_week        — average revenue per weekday across the selected period
      hourly_pattern     — average revenue per hour slot (business hours 07:00–20:00)

    Tanzania is UTC+3, so we shift UTC hours by +3 when computing local hour buckets.
    """
    period_days = (end_date - start_date).days + 1

    # Prior period of the same length (for trend calculation)
    prior_end   = start_date - timedelta(days=1)
    prior_start = prior_end  - timedelta(days=period_days - 1)

    # ── Category Revenue ───────────────────────────────────────────────────────
    # Aggregate TransactionLine revenue by product → category.
    # Lines with deleted products (product=NULL) are excluded; their revenue is
    # treated as uncategorised if any exist via product_name fallback below.
    def _cat_revenue(date_from, date_to):
        return (
            TransactionLine.objects
            .filter(
                transaction__store=store,
                transaction__created_at__date__gte=date_from,
                transaction__created_at__date__lte=date_to,
                transaction__status__in=[
                    Transaction.STATUS_PAID,
                    Transaction.STATUS_CREDIT,
                ],
                product__isnull=False,
            )
            .values("product__category__name")
            .annotate(
                revenue=Sum(
                    models.ExpressionWrapper(
                        models.F("unit_price") * models.F("qty"),
                        output_field=models.IntegerField(),
                    )
                )
            )
        )

    current_cats = list(_cat_revenue(start_date, end_date))
    prior_cats   = list(_cat_revenue(prior_start, prior_end))

    prior_rev_by_cat = {
        row["product__category__name"]: (row["revenue"] or 0)
        for row in prior_cats
    }
    total_rev = sum(row["revenue"] or 0 for row in current_cats) or 1

    category_breakdown = []
    for row in sorted(current_cats, key=lambda r: -(r["revenue"] or 0)):
        name      = row["product__category__name"] or "Uncategorised"
        rev       = row["revenue"] or 0
        prior_rev = prior_rev_by_cat.get(row["product__category__name"], 0)
        trend_pct = round((rev - prior_rev) / prior_rev * 100, 1) if prior_rev else None
        category_breakdown.append({
            "name":      name,
            "revenue":   rev,
            "pct":       round(rev / total_rev * 100, 1),
            "trend_pct": trend_pct,
        })

    # ── Day of Week ────────────────────────────────────────────────────────────
    # Use DailySummary rows (already aggregated) — extract weekday in Python.
    # date.weekday() → 0=Monday … 6=Sunday.
    summaries = list(
        DailySummary.objects.filter(
            store=store,
            date__gte=start_date,
            date__lte=end_date,
        ).values("date", "revenue", "credit_revenue")
    )

    DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_buckets = {i: {"total": 0, "count": 0} for i in range(7)}
    for s in summaries:
        dow = s["date"].weekday()
        dow_buckets[dow]["total"] += (s["revenue"] or 0) + (s["credit_revenue"] or 0)
        dow_buckets[dow]["count"] += 1

    day_of_week = [
        {
            "dow":         i,
            "label":       DOW_LABELS[i],
            "avg_revenue": (
                round(dow_buckets[i]["total"] / dow_buckets[i]["count"])
                if dow_buckets[i]["count"] else 0
            ),
        }
        for i in range(7)
    ]

    # ── Hourly Pattern ─────────────────────────────────────────────────────────
    # Transactions stored in UTC; Tanzania is UTC+3 → local_hour = (utc_hour + 3) % 24.
    # We average by num_days so quieter days don't distort the pattern.
    hourly_qs = (
        Transaction.objects
        .filter(
            store=store,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            status__in=[Transaction.STATUS_PAID, Transaction.STATUS_CREDIT],
        )
        .annotate(utc_hour=ExtractHour("created_at"))
        .annotate(
            local_hour=models.ExpressionWrapper(
                (models.F("utc_hour") + 3) % 24,
                output_field=models.IntegerField(),
            )
        )
        .values("local_hour")
        .annotate(
            total_revenue=Sum("total"),
        )
        .order_by("local_hour")
    )

    hour_map = {row["local_hour"]: (row["total_revenue"] or 0) for row in hourly_qs}
    num_days = max(period_days, 1)

    hourly_pattern = [
        {
            "hour":        hr,
            "label":       f"{hr:02d}:00",
            "avg_revenue": round(hour_map.get(hr, 0) / num_days),
        }
        for hr in range(7, 21)   # 07:00 – 20:00 (14 slots)
    ]

    return {
        "category_breakdown": category_breakdown,
        "day_of_week":        day_of_week,
        "hourly_pattern":     hourly_pattern,
    }


# ── Product Performance ───────────────────────────────────────────────────────

def get_product_performance(
    store,
    start_date: date,
    end_date:   date,
    category:   str | None = None,
) -> list[dict]:
    """
    Full product-level performance table for the /analytics/products sub-page.

    Returns all products sold in the period with:
      units_sold, revenue, cost, profit, margin_pct,
      trend_pct (vs prior period of same length),
      revenue_share_pct (share of total store revenue in period),
      category name.

    Optional category filter: pass category='Grocery' to scope results.

    Reads from TransactionLine for per-product accuracy.
    Products that were soft-deleted still appear as long as their lines exist.
    """
    period_days = (end_date - start_date).days + 1
    prior_end   = start_date - timedelta(days=1)
    prior_start = prior_end  - timedelta(days=period_days - 1)

    line_filter = dict(
        transaction__store=store,
        transaction__status__in=[Transaction.STATUS_PAID, Transaction.STATUS_CREDIT],
    )
    if category:
        line_filter["product__category__name"] = category

    # ── Current period ─────────────────────────────────────────────────────────
    # Include lines where product FK is null (deleted product) keyed by product_name
    current_qs = list(
        TransactionLine.objects
        .filter(
            **line_filter,
            transaction__created_at__date__gte=start_date,
            transaction__created_at__date__lte=end_date,
        )
        .values(
            "product_id",
            "product_name",
            "product_sku",
            "product__category__name",
        )
        .annotate(
            units=Sum("qty"),
            revenue=Sum(
                models.ExpressionWrapper(
                    models.F("unit_price") * models.F("qty"),
                    output_field=models.IntegerField(),
                )
            ),
            cost=Sum(
                models.ExpressionWrapper(
                    models.F("unit_cost") * models.F("qty"),
                    output_field=models.IntegerField(),
                )
            ),
        )
        .order_by("-revenue")
    )

    # ── Prior period (for trend) ───────────────────────────────────────────────
    prior_qs = (
        TransactionLine.objects
        .filter(
            **line_filter,
            transaction__created_at__date__gte=prior_start,
            transaction__created_at__date__lte=prior_end,
        )
        .values("product_id", "product_name")
        .annotate(
            revenue=Sum(
                models.ExpressionWrapper(
                    models.F("unit_price") * models.F("qty"),
                    output_field=models.IntegerField(),
                )
            ),
        )
    )

    # Key prior revenue by product_id (with product_name fallback for deleted products)
    prior_rev: dict[str, int] = {}
    for row in prior_qs:
        key = str(row["product_id"]) if row["product_id"] else row["product_name"]
        prior_rev[key] = row["revenue"] or 0

    total_rev = sum(row["revenue"] or 0 for row in current_qs) or 1

    results = []
    for row in current_qs:
        rev     = row["revenue"] or 0
        cost    = row["cost"]    or 0
        profit  = rev - cost
        key     = str(row["product_id"]) if row["product_id"] else row["product_name"]
        p_rev   = prior_rev.get(key, 0)

        results.append({
            "product_id":        str(row["product_id"]) if row["product_id"] else None,
            "product_name":      row["product_name"],
            "product_sku":       row["product_sku"],
            "category":          row["product__category__name"] or "Uncategorised",
            "units_sold":        row["units"] or 0,
            "revenue":           rev,
            "cost":              cost,
            "profit":            profit,
            "margin_pct":        round(profit / rev * 100, 1) if rev else 0.0,
            "trend_pct":         round((rev - p_rev) / p_rev * 100, 1) if p_rev else None,
            "revenue_share_pct": round(rev / total_rev * 100, 1),
        })

    return results


# ── Customer Analytics ────────────────────────────────────────────────────────

def get_customer_analytics(store, start_date: date, end_date: date) -> dict:
    """
    Customer analytics for the /analytics/customers sub-page.

    Sections:
      daily_visits       — [{date, label, total, new_customers, returning}]
      segments           — [{segment, count, spend, pct}]
      retention_cohorts  — last-4-month cohorts [{month, new, m1, m2, m3}]
      top_customers      — top 20 customers by spend in period

    "New" customers: first transaction at this store falls within the range.
    "Returning" customers: had at least one transaction before the range start.
    """
    active_statuses = [Transaction.STATUS_PAID, Transaction.STATUS_CREDIT]

    # ── Daily Visits ───────────────────────────────────────────────────────────
    # Step 1: For every registered customer, get their ALL-TIME first transaction
    #         date at this store, so we know if they are "new" during the range.
    first_txn_per_customer = dict(
        Transaction.objects
        .filter(store=store, customer__isnull=False, status__in=active_statuses)
        .values("customer_id")
        .annotate(first_date=Min("created_at"))
        .values_list("customer_id", "first_date")
    )

    # Step 2: All (customer_id, date) pairs where a registered customer transacted
    #         in the range.
    txn_dates = list(
        Transaction.objects
        .filter(
            store=store,
            customer__isnull=False,
            status__in=active_statuses,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .annotate(txn_date=TruncDate("created_at"))
        .values("customer_id", "txn_date")
        .distinct()
    )

    # Step 3: Per-day unique customer counts; classify each as new or returning
    day_new       = defaultdict(int)
    day_returning = defaultdict(int)

    for row in txn_dates:
        cid      = row["customer_id"]
        day      = row["txn_date"].date() if hasattr(row["txn_date"], "date") else row["txn_date"]
        first_dt = first_txn_per_customer.get(cid)

        if first_dt is None:
            # Should not happen, but treat as returning
            day_returning[day] += 1
            continue

        first_d = first_dt.date() if hasattr(first_dt, "date") else first_dt
        if first_d >= start_date:
            # Customer is new during the range; only count as "new" on their first day
            if first_d == day:
                day_new[day] += 1
            else:
                day_returning[day] += 1
        else:
            day_returning[day] += 1

    # Build zero-filled day series
    daily_visits = []
    current = start_date
    while current <= end_date:
        new_c = day_new.get(current, 0)
        ret_c = day_returning.get(current, 0)
        daily_visits.append({
            "date":          current.isoformat(),
            "label":         current.strftime("%-d %b"),
            "total":         new_c + ret_c,
            "new_customers": new_c,
            "returning":     ret_c,
        })
        current += timedelta(days=1)

    # ── Segments ───────────────────────────────────────────────────────────────
    # Distinct customers who transacted in range, grouped by their current segment
    seg_agg = list(
        Transaction.objects
        .filter(
            store=store,
            customer__isnull=False,
            status__in=active_statuses,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .values("customer__segment")
        .annotate(
            spend=Sum("total"),
            count=Count("customer_id", distinct=True),
        )
    )

    seg_total = sum(r["count"] or 0 for r in seg_agg) or 1
    segments = [
        {
            "segment": row["customer__segment"] or "Unknown",
            "count":   row["count"]  or 0,
            "spend":   row["spend"]  or 0,
            "pct":     round((row["count"] or 0) / seg_total * 100, 1),
        }
        for row in sorted(seg_agg, key=lambda r: -(r["count"] or 0))
    ]

    # ── Retention Cohorts ─────────────────────────────────────────────────────
    # Cohort M = customers whose FIRST EVER transaction at this store was in month M.
    # m1, m2, m3 = count of those customers who came back in M+1, M+2, M+3.
    today = date.today()

    # Build last 4 complete-ish months (current month included as partial)
    cohort_month_starts = []
    for i in range(3, -1, -1):
        year, month = today.year, today.month - i
        while month <= 0:
            month += 12
            year  -= 1
        cohort_month_starts.append(date(year, month, 1))

    # (customer_id, month_start_date) pairs of all transactions at this store
    # TruncMonth returns a datetime; we only need (year, month)
    customer_month_pairs = list(
        Transaction.objects
        .filter(store=store, customer__isnull=False, status__in=active_statuses)
        .annotate(month=TruncMonth("created_at"))
        .values_list("customer_id", "month")
        .distinct()
    )

    # Set of (customer_id, (year, month)) for fast lookup
    active_in_month: set[tuple] = set()
    for cid, m_dt in customer_month_pairs:
        active_in_month.add((cid, (m_dt.year, m_dt.month)))

    def _next_month(d: date, n: int) -> date:
        year, month = d.year, d.month + n
        while month > 12:
            month -= 12
            year  += 1
        return date(year, month, 1)

    cohort_data = []
    for cm in cohort_month_starts:
        nm = _next_month(cm, 1)

        # New customers = those whose all-time first transaction was THIS month
        cohort_ids = {
            cid
            for cid, first_dt in first_txn_per_customer.items()
            if first_dt is not None
            and cm <= (first_dt.date() if hasattr(first_dt, "date") else first_dt) < nm
        }

        def _ret_count(offset: int) -> int:
            """How many cohort_ids came back `offset` months after cm?"""
            target = _next_month(cm, offset)
            # Only report if target month is in the past (completed)
            if target >= date(today.year, today.month, 1):
                return 0
            return sum(
                1 for cid in cohort_ids
                if (cid, (target.year, target.month)) in active_in_month
            )

        cohort_data.append({
            "month": cm.strftime("%b"),
            "year":  cm.year,
            "new":   len(cohort_ids),
            "m1":    _ret_count(1),
            "m2":    _ret_count(2),
            "m3":    _ret_count(3),
        })

    # ── Top Customers ─────────────────────────────────────────────────────────
    top_qs = list(
        Transaction.objects
        .filter(
            store=store,
            customer__isnull=False,
            status__in=active_statuses,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .values("customer_id", "customer__name", "customer__avatar_hue")
        .annotate(
            period_spend=Sum("total"),
            visit_count=Count("id"),
            last_txn=Max("created_at"),
        )
        .order_by("-period_spend")[:20]
    )

    top_customers = []
    for row in top_qs:
        spend   = row["period_spend"] or 0
        visits  = row["visit_count"]  or 0
        last_dt = row["last_txn"]
        last_d  = last_dt.date() if last_dt and hasattr(last_dt, "date") else last_dt
        top_customers.append({
            "customer_id":   str(row["customer_id"]),
            "name":          row["customer__name"],
            "visits":        visits,
            "spent":         spend,
            "avg_ticket":    spend // visits if visits else 0,
            "last_seen_days": (today - last_d).days if last_d else None,
            "avatar_hue":    row["customer__avatar_hue"] or 200,
        })

    return {
        "daily_visits":       daily_visits,
        "segments":           segments,
        "retention_cohorts":  cohort_data,
        "top_customers":      top_customers,
    }


# ── Cashflow ──────────────────────────────────────────────────────────────────

def get_cashflow(store, start_date: date, end_date: date) -> dict:
    """
    Cashflow view data for the /analytics/cashflow sub-page.

    Sections:
      totals           — {inflow, cogs, opex, net}
      daily            — [{date, label, inflow, cogs, opex, net}] (day-by-day)
      running_balance  — [{date, label, balance}] cumulative net from period start
      expense_breakdown — [{name, amount, pct}] COGS is the only tracked expense
      payment_inflow   — same as payment-mix (revenue by method)
      credit_outstanding — {total, customer_count, overdue_count}

    NOTE: OPEX (operating expenses: rent, wages, transport) is NOT currently
    tracked in the data model. The `opex` field returns 0 with a note.
    A future "Expenses" feature will populate this field.
    """
    # ── Daily Cashflow from DailySummary ───────────────────────────────────────
    summaries = {
        s.date: s
        for s in DailySummary.objects.filter(
            store=store,
            date__gte=start_date,
            date__lte=end_date,
        )
    }

    daily = []
    running_bal = 0
    running_balance = []
    total_inflow = total_cogs = total_net = 0

    current = start_date
    while current <= end_date:
        s = summaries.get(current)
        inflow = (s.revenue + s.credit_revenue) if s else 0
        cogs   = s.cost_total                    if s else 0
        net    = inflow - cogs                   # OPEX = 0 for now

        total_inflow += inflow
        total_cogs   += cogs
        total_net    += net
        running_bal  += net

        lbl = current.strftime("%-d %b")
        daily.append({
            "date":   current.isoformat(),
            "label":  lbl,
            "inflow": inflow,
            "cogs":   cogs,
            "opex":   0,       # Not tracked yet
            "net":    net,
        })
        running_balance.append({
            "date":    current.isoformat(),
            "label":   lbl,
            "balance": running_bal,
        })
        current += timedelta(days=1)

    # ── Expense Breakdown ─────────────────────────────────────────────────────
    # Only COGS is tracked; OPEX categories will be added when expense tracking ships.
    total_expenses = total_cogs  # will grow when OPEX is tracked
    expense_breakdown = [
        {
            "name":   "Cost of Goods",
            "amount": total_cogs,
            "pct":    round(total_cogs  / total_inflow * 100, 1) if total_inflow else 0,
        },
    ]
    # Placeholder rows (0) so the UI can show the full breakdown structure
    for placeholder in ["Rent & Utilities", "Staff Wages", "Transport", "Other OPEX"]:
        expense_breakdown.append({
            "name":   placeholder,
            "amount": 0,
            "pct":    0.0,
            "_note": "OPEX tracking not yet enabled",
        })

    # ── Payment Inflow (reuse existing helper) ─────────────────────────────────
    payment_inflow = get_payment_mix(store, start_date, end_date)

    # ── Outstanding Credit ─────────────────────────────────────────────────────
    # Lazy import to avoid circular dependency at module load
    try:
        from apps.credits.models import CreditTab
        open_tabs = CreditTab.objects.filter(
            store=store,
            status__in=[CreditTab.STATUS_OPEN, CreditTab.STATUS_PARTIAL],
        )
        credit_agg = open_tabs.aggregate(
            total=Sum(
                models.ExpressionWrapper(
                    models.F("amount") - models.F("amount_paid"),
                    output_field=models.IntegerField(),
                )
            ),
            customers=Count("customer_id", distinct=True),
        )
        from django.utils import timezone as tz
        overdue_count = open_tabs.filter(due_date__lt=tz.now().date()).count()
        credit_outstanding = {
            "total":          credit_agg["total"]     or 0,
            "customer_count": credit_agg["customers"] or 0,
            "overdue_count":  overdue_count,
        }
    except Exception:
        credit_outstanding = {"total": 0, "customer_count": 0, "overdue_count": 0}

    return {
        "totals": {
            "inflow":    total_inflow,
            "cogs":      total_cogs,
            "opex":      0,
            "net":       total_net,
            "net_margin_pct": round(total_net / total_inflow * 100, 1) if total_inflow else 0.0,
            "opex_note": "Operating expense tracking not yet enabled.",
        },
        "daily":              daily,
        "running_balance":    running_balance,
        "expense_breakdown":  expense_breakdown,
        "payment_inflow":     payment_inflow,
        "credit_outstanding": credit_outstanding,
    }


# ── Dashboard Data ────────────────────────────────────────────────────────────

def get_dashboard_data(store) -> dict:
    """
    All widgets for the main dashboard page (/) in one call.

    Returns:
      kpis_today   — today's revenue, profit, tickets, outstanding credit
      hourly_today — today's revenue by local hour (for the sales-by-hour chart)
      payment_mix  — today's payment method breakdown
      top_products — top 6 products for the last 7 days
      low_stock    — products at or below min_stock

    NOTE: recent_transactions is served by the existing
    GET /api/v1/transactions/ endpoint (page 1, latest first).
    """
    today = date.today()

    # ── Today's KPIs ──────────────────────────────────────────────────────────
    kpis_today = get_kpi_summary(store, today, today)

    # ── Hourly Revenue (today, local TZ) ──────────────────────────────────────
    # Shift UTC → EAT (+3) using the same approach as get_sales_breakdown
    hourly_qs = (
        Transaction.objects
        .filter(
            store=store,
            created_at__date=today,
            status__in=[Transaction.STATUS_PAID, Transaction.STATUS_CREDIT],
        )
        .annotate(utc_hour=ExtractHour("created_at"))
        .annotate(
            local_hour=models.ExpressionWrapper(
                (models.F("utc_hour") + 3) % 24,
                output_field=models.IntegerField(),
            )
        )
        .values("local_hour")
        .annotate(
            revenue=Sum("total"),
            txn_count=Count("id"),
        )
        .order_by("local_hour")
    )
    hour_map = {row["local_hour"]: row for row in hourly_qs}

    hourly_today = [
        {
            "hour":      hr,
            "label":     f"{hr:02d}:00",
            "revenue":   (hour_map.get(hr, {}).get("revenue")   or 0),
            "txn_count": (hour_map.get(hr, {}).get("txn_count") or 0),
        }
        for hr in range(7, 21)
    ]

    # ── Payment Mix (today) ────────────────────────────────────────────────────
    payment_mix_today = get_payment_mix(store, today, today)

    # ── Top Products (last 7 days) ─────────────────────────────────────────────
    seven_days_ago = today - timedelta(days=6)
    top_products = get_top_products(store, seven_days_ago, today, limit=6)

    # ── Low Stock ─────────────────────────────────────────────────────────────
    from apps.inventory.models import Product
    low_stock = list(
        Product.objects
        .filter(store=store, is_active=True, stock__lte=models.F("min_stock"))
        .order_by("stock")
        .values("id", "name", "sku", "stock", "min_stock")[:10]
    )
    for p in low_stock:
        p["id"]     = str(p["id"])
        p["status"] = "critical" if p["stock"] == 0 else (
            "low" if p["stock"] <= p["min_stock"] // 2 else "low"
        )

    # ── Outstanding Credit (quick KPI) ────────────────────────────────────────
    try:
        from apps.credits.models import CreditTab
        open_tabs = CreditTab.objects.filter(
            store=store,
            status__in=[CreditTab.STATUS_OPEN, CreditTab.STATUS_PARTIAL],
        )
        cred_agg = open_tabs.aggregate(
            total=Sum(
                models.ExpressionWrapper(
                    models.F("amount") - models.F("amount_paid"),
                    output_field=models.IntegerField(),
                )
            ),
            customers=Count("customer_id", distinct=True),
        )
        from django.utils import timezone as tz
        overdue = open_tabs.filter(due_date__lt=tz.now().date()).count()
        credit_kpi = {
            "total":         cred_agg["total"]     or 0,
            "customer_count":cred_agg["customers"] or 0,
            "overdue_count": overdue,
        }
    except Exception:
        credit_kpi = {"total": 0, "customer_count": 0, "overdue_count": 0}

    return {
        "kpis_today":    kpis_today,
        "hourly_today":  hourly_today,
        "payment_mix":   payment_mix_today,
        "top_products":  top_products,
        "low_stock":     low_stock,
        "credit_kpi":    credit_kpi,
    }


# ── Import for F/ExpressionWrapper ──────────────────────────────────────────
from django.db import models
