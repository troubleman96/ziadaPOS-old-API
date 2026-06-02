# apps/analytics — Aggregated Analytics & Business Intelligence

## What this app does

`apps/analytics` provides all the data that powers the analytics section of the Ziada POS UI. It owns the `DailySummary` model (pre-aggregated daily stats) and a library of service functions that compute KPIs, trends, product performance, customer cohorts, cashflow, and dashboard data.

The app follows a two-tier data strategy:
- **Fast path:** Read from `DailySummary` (pre-aggregated, one row per store per day) for KPIs, trends, and payment mix
- **Raw path:** Query `Transaction` and `TransactionLine` directly for granular breakdowns (product performance, customer analytics, hourly patterns, cashflow)

**UI pages this app powers:**
- `/analytics/overview` — KPI strip + revenue trend chart + payment mix donut + top products
- `/analytics/sales` — category revenue breakdown, day-of-week averages, hourly traffic pattern
- `/analytics/products` — full product performance table with margin, trend vs prior period, category filter
- `/analytics/customers` — daily visits, segment breakdown, retention cohort table, top customers
- `/analytics/cashflow` — daily inflow/COGS/net, running balance, payment method breakdown
- Dashboard (main) — today's KPIs, hourly chart, payment mix, top products, low stock, credit KPIs

---

## Model: `DailySummary`

Pre-aggregated daily sales statistics for one store and one calendar day.

**Why pre-aggregate?**
Scanning all transactions on every analytics page load gets slow as data grows (a store processing 100 transactions/day will have 36,500 rows/year). `DailySummary` reduces a 90-day trend query to reading 90 rows.

**When is it updated?**
1. Automatically via Django signal: every time a `Transaction` is saved, `rebuild_daily_summary(store, today)` is called (wired in `AnalyticsConfig.ready()`)
2. Manually via management command: `python manage.py rebuild_daily_summaries` for backfilling

**One row = one day × one store.** `unique_together = [("store", "date")]`

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `store` | FK → Store (CASCADE) | Which store. |
| `date` | DateField | Calendar day this row covers. |
| `transaction_count` | PositiveIntegerField | Paid + credit transactions (not refunded/void). |
| `customer_count` | PositiveIntegerField | Distinct registered customers who transacted. |
| `revenue` | PositiveIntegerField | Sum of `total` for `paid` transactions (TZS). |
| `credit_revenue` | PositiveIntegerField | Sum of `total` for `credit` transactions (TZS). |
| `cost_total` | PositiveIntegerField | Sum of `cost_total` for paid transactions (COGS). |
| `profit` | IntegerField | Sum of `profit` for paid transactions. Can be negative. |
| `tax_collected` | PositiveIntegerField | Sum of `tax_amount` for paid transactions. |
| `refund_total` | PositiveIntegerField | Sum of `total` for refunded transactions. |
| `cash_revenue` | PositiveIntegerField | Revenue from Cash method (TZS). |
| `mpesa_revenue` | PositiveIntegerField | Revenue from M-Pesa (TZS). |
| `tigo_revenue` | PositiveIntegerField | Revenue from Tigo Pesa (TZS). |
| `bank_revenue` | PositiveIntegerField | Revenue from Bank (TZS). |
| `credit_issued` | PositiveIntegerField | Amount issued on credit this day (same as `credit_revenue`). |

**Computed properties:**

```python
summary.margin_pct   # float: profit / (revenue + credit_revenue) * 100
summary.avg_ticket   # int: (revenue + credit_revenue) / transaction_count
```

**DB index:** `(store, date)` — the primary query pattern.

---

## Service Functions (`services.py`)

### `rebuild_daily_summary(store, target_date) → DailySummary`

Idempotent: creates or overwrites the DailySummary row for the given date. Queries `Transaction` directly for all paid/credit/refunded records on that day, then upserts via `update_or_create`. Called on every transaction save via signal.

---

### `get_revenue_trend(store, start_date, end_date) → list[dict]`

Day-by-day revenue series for charts. Reads from `DailySummary`. **Fills in zero** for days with no summary row (store closed / no sales that day) so the chart has a continuous x-axis.

```python
[
  {"date": "2026-05-01", "label": "1 May", "revenue": 1200000, "profit": 264000, "transactions": 42},
  {"date": "2026-05-02", "label": "2 May", "revenue": 0, "profit": 0, "transactions": 0},
  ...
]
```

---

### `get_payment_mix(store, start_date, end_date) → list[dict]`

Revenue breakdown by payment method (for the donut chart). Reads from `DailySummary`. Returns amounts and percentages:

```python
[
  {"method": "M-Pesa",   "amount": 4800000, "pct": 48.0},
  {"method": "Cash",     "amount": 2800000, "pct": 28.0},
  {"method": "Credit",   "amount": 1200000, "pct": 12.0},
  {"method": "Tigo Pesa","amount": 800000,  "pct": 8.0},
  {"method": "Bank",     "amount": 400000,  "pct": 4.0},
]
```

---

### `get_top_products(store, start_date, end_date, limit=10) → list[dict]`

Most sold products by revenue in the date range. Queries `TransactionLine` directly (not DailySummary). Returns units_sold, revenue, and average price for each product.

---

### `get_kpi_summary(store, start_date, end_date) → dict`

Aggregate KPIs for the analytics header cards. Reads from `DailySummary`. Also computes comparison against the prior equal-length period to derive `trend_pct` values.

```python
{
  "revenue": 4850000,
  "revenue_trend": +12.3,        # % change vs prior period
  "profit": 820000,
  "margin_pct": 16.9,
  "transactions": 87,
  "avg_ticket": 55747,
  "customers": 34,
}
```

---

### `get_sales_breakdown(store, start_date, end_date) → dict`

Powers the `/analytics/sales` sub-page. Three sections:

**Category breakdown** — queries `TransactionLine → Product → Category`. Returns revenue, units, and `trend_pct` vs prior period for each category.

**Day-of-week averages** — groups `DailySummary` by `date.weekday()` in Python. Returns average daily revenue per day of week (Mon–Sun). Useful for spotting that Saturday is the biggest sales day.

**Hourly pattern** — annotates `Transaction` with `local_hour = (ExtractHour(created_at) + 3) % 24` (UTC+3 Tanzania). Returns average revenue per hour for 07:00–20:00. Uses a DB-level `ExpressionWrapper` so the timezone conversion happens in SQL.

---

### `get_product_performance(store, start_date, end_date, category=None) → list[dict]`

Powers the `/analytics/products` sub-page. For each product in the store:

```python
{
  "id": "uuid",
  "name": "Unga wa Sembe 10kg",
  "sku": "UWS-10",
  "category": "Grocery",
  "units_sold": 42,
  "revenue": 1197000,
  "cost": 924000,
  "profit": 273000,
  "margin_pct": 22.8,
  "revenue_share_pct": 8.3,   # this product's % of total revenue
  "trend_pct": +15.2,         # vs prior equal period
}
```

Optional `category=` filter narrows to one category. Products with zero sales in the period are included (units_sold=0). Sorted by `revenue` descending by default; the view accepts `?sort=units|margin|profit`.

---

### `get_customer_analytics(store, start_date, end_date) → dict`

Powers the `/analytics/customers` sub-page. Four sections:

**Daily visits** — `Transaction` grouped by date. New customers (first transaction ever at this store) vs returning.

**Segments** — current count per segment from the `Customer` table.

**Retention cohorts** — for each of the last 4 months:
- Identify customers whose first transaction was in that month (the "cohort")
- Count what % of them returned in M+1, M+2, M+3
- Result: a 4-row table showing cohort month, cohort size, and return rates

**Top customers** — top 20 registered customers by spend in the period, sorted descending.

---

### `get_cashflow(store, start_date, end_date) → dict`

Powers the `/analytics/cashflow` sub-page.

```python
{
  "totals": {
    "inflow": 4850000,       # total revenue (paid + credit)
    "cogs": 3200000,         # cost of goods sold
    "gross_profit": 1650000,
    "tax": 630000,
    "opex": 0,               # not tracked — see note below
    "net_cashflow": 1020000,
    "opex_note": "Expense tracking not yet enabled in this version."
  },
  "daily": [...],            # day-by-day inflow/cogs/net series
  "running_balance": [...],  # cumulative net from period start
  "payment_inflow": [...],   # inflow by payment method
  "credit_outstanding": int, # sum of open credit tabs
}
```

**OPEX note:** Operating expenses (rent, wages, transport) are not modeled in the current data schema. `opex` returns 0 with an explanatory note field. This keeps the API contract complete so the frontend can render placeholder rows while not returning misleading data.

---

### `get_dashboard_data(store) → dict`

Powers the dashboard page in a single API call. Returns:

```python
{
  "kpis_today": {
    "revenue": 842000,
    "profit": 147350,
    "transactions": 23,
    "avg_ticket": 36609,
    "margin_pct": 17.5,
  },
  "hourly_today": [...],    # revenue by local hour 07:00-20:00
  "payment_mix": [...],     # payment method breakdown (this month)
  "top_products": [...],    # top 5 products by units sold this week
  "low_stock": [...],       # products at or below min_stock
  "credit_kpi": {
    "total_outstanding": 850000,
    "overdue_count": 3,
    "recovered_month": 200000,
  }
}
```

---

## API Endpoints

All routes mount at `/api/v1/analytics/`. All endpoints support:
- `?range=7d|30d|90d|ytd` — preset date ranges
- `?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` — explicit range

### Original endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/overview/` | KPIs + trend + payment mix + top products in one call |
| GET | `/summary/` | KPIs only (lighter) |
| GET | `/trend/` | Day-by-day revenue series |
| GET | `/payment-mix/` | Revenue by method (donut chart) |
| GET | `/top-products/` | Most sold products by revenue |

### Sub-page endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/sales/` | Category breakdown, DOW averages, hourly pattern |
| GET | `/products/` | Full product performance table |
| GET | `/customers/` | Visits, segments, cohorts, top customers |
| GET | `/cashflow/` | Daily inflow/COGS/net, running balance, expenses |

Additional query params:
- `/products/?category=Grocery` — filter by category name
- `/products/?sort=revenue|units|margin|profit` — sort order

### Dashboard endpoint

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/dashboard/` | All dashboard widgets in one call (no date range — always "today") |

---

## Signals & AppConfig (`apps.py`, `signals.py`)

`AnalyticsConfig.ready()` wires the Transaction signal:

```python
# apps/analytics/apps.py
def ready(self):
    from apps.transactions.models import Transaction
    from django.db.models.signals import post_save
    from .signals import update_daily_summary_for_today
    post_save.connect(update_daily_summary_for_today, sender=Transaction)
```

The signal handler calls `rebuild_daily_summary(transaction.store, today)` on every Transaction save. This ensures `DailySummary` is always current without requiring a nightly batch job.

**Performance note:** On a very high-volume store (1000+ transactions/day), this signal fires 1000+ times per day, each time doing a full re-aggregation of today's transactions. At typical African corner-shop volumes (50-300 transactions/day), this is negligible. If volume is higher, consider debouncing the signal or switching to a Celery task.

---

## Admin (`admin.py`)

`DailySummary` is registered in the admin as a read-only model (no add/edit via admin — it's always rebuilt from transactions). Useful for debugging analytics discrepancies.

---

## Design Decisions

**Why DailySummary instead of materialised views?**
Django doesn't have built-in support for DB-level materialised views across all databases. A Django model row is portable (works with both SQLite in dev and PostgreSQL in prod), debuggable in the admin, and refreshable via management command. The tradeoff is that it's slightly more complex to keep in sync — the signal handles the real-time update.

**Why not use the DailySummary for all analytics?**
`DailySummary` stores totals but not per-product or per-customer data. For product performance and customer analytics, we need `TransactionLine` level detail. The service layer makes a deliberate choice: use `DailySummary` where it covers the need (trend, KPIs, payment mix) and fall back to raw queries where it doesn't.

**Why is the hourly chart in Tanzania timezone done at the DB level?**
Transactions are stored in UTC. Rather than requiring a Python loop to convert each timestamp, we use:
```python
ExpressionWrapper((ExtractHour("created_at") + 3) % 24, output_field=IntegerField())
```
This shifts UTC hours to Africa/Dar_es_Salaam (UTC+3) in a single SQL expression, compatible with both SQLite and PostgreSQL.

**Why 4 retention cohort months?**
Retention analysis needs at least 3-4 months of data to be meaningful. More months would extend the query significantly. 4 months gives a good view of the retention curve (M+1, M+2, M+3) while keeping the query manageable.

---

## Common Gotchas

1. **`DailySummary` may be missing for days before it was first populated.** A store that started using Ziada mid-month will have no DailySummary rows for earlier days. The trend service fills these with 0 — which is correct, but only if the transactions were also missing (not if old transactions exist but no summary was ever built). Run `python manage.py rebuild_daily_summaries` after onboarding a store with historical data.

2. **The hourly chart uses `(hour + 3) % 24` for UTC+3.** This is correct for standard Tanzania time but doesn't account for DST (Tanzania doesn't observe DST, so this is fine). If the app is ever deployed in a DST-observing timezone, this calculation must change.

3. **`get_kpi_summary` trend comparison uses prior equal-length period.** For a 30-day range ending today, the prior period is the 30 days before that. For a `?range=month` (current calendar month), the prior period is last calendar month. These may have different lengths — January vs February. The trend percentage should be interpreted as directional, not precisely comparative.

4. **The `/dashboard/` endpoint ignores date range params.** Dashboard data is always "today" (for KPIs and hourly) or "last 7 days" (for top products and payment mix). Date range params are silently ignored.

5. **Product performance returns ALL products, not just those with sales.** A product with zero sales in the period still appears with `units_sold: 0`. This matches the frontend's expectation of a complete product table, not just a top-sellers list.
