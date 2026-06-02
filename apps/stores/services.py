"""
apps/stores/services.py

All business logic for the stores management page.

Functions:
  get_store_today_kpis(store)     → today's revenue + transaction count
  get_store_week_data(store)      → [Mon…Sun] revenue array for current ISO week
  get_store_week_breakdown(store) → full per-day dict list for the detail chart
  get_store_manager(store)        → User with role=manager, or None
  get_staff_on_duty_count(store)  → count of active staff at this store
  get_org_stats(organisation)     → aggregate KPI strip for the list page header
  get_staff_roster(store)         → list of staff dicts with on-duty flag
"""

from datetime import date, timedelta


# ── Today's KPIs ──────────────────────────────────────────────────────────────

def get_store_today_kpis(store) -> dict:
    """
    Return today's revenue and transaction count for a store.

    Reads from DailySummary for speed. Falls back to 0 if today's
    summary hasn't been built yet (e.g. no transactions yet today).
    """
    from apps.analytics.models import DailySummary

    today = date.today()
    try:
        s = DailySummary.objects.get(store=store, date=today)
        return {
            "today_revenue": (s.revenue or 0) + (s.credit_revenue or 0),
            "today_txns":    s.transaction_count or 0,
        }
    except DailySummary.DoesNotExist:
        return {"today_revenue": 0, "today_txns": 0}


# ── Week sparkline ────────────────────────────────────────────────────────────

def get_store_week_data(store) -> list[int]:
    """
    Return a 7-element list of daily revenue for the current ISO week.
    Index 0 = Monday, 6 = Sunday. Future days return 0.
    """
    from apps.analytics.models import DailySummary

    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday of this week

    summaries = {
        s.date: (s.revenue or 0) + (s.credit_revenue or 0)
        for s in DailySummary.objects.filter(
            store=store,
            date__gte=week_start,
            date__lte=week_start + timedelta(days=6),
        )
    }

    return [
        summaries.get(week_start + timedelta(days=i), 0)
        for i in range(7)
    ]


# ── Full week breakdown (for detail page chart) ───────────────────────────────

def get_store_week_breakdown(store) -> list[dict]:
    """
    Return a full per-day breakdown for the current ISO week.
    Used by the store detail overview tab chart.

    Each entry: { date, day, revenue, transactions, is_future }
    """
    from apps.analytics.models import DailySummary

    today      = date.today()
    week_start = today - timedelta(days=today.weekday())
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    summaries = {
        s.date: s
        for s in DailySummary.objects.filter(
            store=store,
            date__gte=week_start,
            date__lte=week_start + timedelta(days=6),
        )
    }

    breakdown = []
    for i, label in enumerate(day_labels):
        d = week_start + timedelta(days=i)
        s = summaries.get(d)
        revenue = ((s.revenue or 0) + (s.credit_revenue or 0)) if s else 0
        breakdown.append({
            "date":         d.isoformat(),
            "day":          label,
            "revenue":      revenue,
            "transactions": s.transaction_count if s else 0,
            "is_future":    d > today,
        })

    # Compute avg over days that have data
    active_days = [row for row in breakdown if not row["is_future"] and row["revenue"] > 0]
    avg = sum(r["revenue"] for r in active_days) // len(active_days) if active_days else 0
    for row in breakdown:
        row["vs_avg_pct"] = (
            round((row["revenue"] - avg) / avg * 100, 1)
            if avg and not row["is_future"] and row["revenue"] > 0
            else None
        )

    return breakdown


# ── Manager lookup ────────────────────────────────────────────────────────────

def get_store_manager(store):
    """Return the first active manager at this store, or None."""
    return store.staff.filter(role="manager", is_active=True).first()


# ── Staff on duty ─────────────────────────────────────────────────────────────

def get_staff_on_duty_count(store) -> int:
    """
    Count active staff at this store.
    Since there is no shift model yet, all active users are considered
    on duty while the store is open.
    """
    return store.staff.filter(is_active=True).count()


# ── Staff roster (detail page) ────────────────────────────────────────────────

def get_staff_roster(store) -> list[dict]:
    """
    Return all staff for this store with on-duty status.

    Since there is no shift/attendance model, staff are marked
    on-duty when the store is open, off-duty when closed/paused.
    """
    is_open  = store.status == "open"
    all_staff = list(
        store.staff.filter(is_active=True).order_by("role", "first_name")
    )

    result = []
    for user in all_staff:
        result.append({
            "id":       user.id,
            "name":     user.get_full_name() or user.username,
            "role":     user.get_role_display() if hasattr(user, "get_role_display") else user.role.capitalize(),
            "status":   "on-duty" if is_open else "off-duty",
            "since":    "—",   # populated when shift tracking is added
            "phone":    user.phone,
            "avatar_hue": user.avatar_hue,
        })

    return result


# ── Org-level stats (list page header strip) ─────────────────────────────────

def get_org_stats(organisation) -> dict:
    """
    Aggregate KPI header stats across all active stores in the organisation.

    Called for GET /api/v1/stores/stats/
    """
    stores = list(organisation.stores.filter(is_active=True))

    open_count   = sum(1 for s in stores if s.status == "open")
    closed_count = sum(1 for s in stores if s.status == "closed")
    paused_count = sum(1 for s in stores if s.status == "paused")

    total_revenue    = 0
    total_txns       = 0
    total_staff      = 0

    for store in stores:
        kpis = get_store_today_kpis(store)
        total_revenue += kpis["today_revenue"]
        total_txns    += kpis["today_txns"]
        total_staff   += get_staff_on_duty_count(store)

    return {
        "total_stores":  len(stores),
        "open_count":    open_count,
        "closed_count":  closed_count,
        "paused_count":  paused_count,
        "total_revenue": total_revenue,
        "total_txns":    total_txns,
        "staff_on_duty": total_staff,
    }
