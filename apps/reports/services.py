"""
apps/reports/services.py

Report data generators and CSV builder for the reports app.

Each generator function returns a standardised dict with the report data.
That dict is used to:
  1. Build a CSV response (via build_csv_response)
  2. Return structured JSON for PDF rendering (frontend uses jsPDF or similar)
  3. Create a ReportExport audit record

Report generators:
  generate_sales_summary(store, start_date, end_date)     → Sales Summary
  generate_inventory_valuation(store)                     → Inventory Valuation
  generate_tax_statement(store, start_date, end_date)     → Tax Statement
  generate_credit_aged_debtors(store)                     → Credit Aged Debtors

Utilities:
  get_report_data(report_type, store, start_date, end_date) → dispatcher
  build_csv(report_type, data)                             → CSV string
  parse_range_for_report(query_params)                     → (start, end, label)
  compute_next_send(frequency, from_dt)                   → next datetime
"""

import csv
import io
from datetime import date, datetime, timedelta

from django.db.models import Count, F, Sum
from django.db.models import ExpressionWrapper, IntegerField

from apps.analytics.services import (
    get_kpi_summary,
    get_payment_mix,
    get_revenue_trend,
    get_top_products,
    parse_date_range,
)
from apps.transactions.models import Transaction, TransactionLine


# ── Date range helpers ────────────────────────────────────────────────────────

def parse_range_for_report(query_params) -> tuple[date, date, str]:
    """
    Parse date range from query params and return (start, end, period_label).

    The period_label is the human-readable string shown in the history table,
    e.g. "1 – 24 May 2026", "April 2026", "1 Jan – 25 May 2026".
    """
    start, end = parse_date_range(query_params)

    # Build a readable label
    if start.year == end.year and start.month == end.month:
        if start.day == 1 and end == _last_day_of_month(start):
            label = start.strftime("%B %Y")                     # "April 2026"
        else:
            label = f"{start.day}–{end.day} {end.strftime('%b %Y')}"  # "1–24 May 2026"
    elif start.year == end.year:
        label = f"{start.strftime('%-d %b')} – {end.strftime('%-d %b %Y')}"
    else:
        label = f"{start.strftime('%-d %b %Y')} – {end.strftime('%-d %b %Y')}"

    return start, end, label


def _last_day_of_month(d: date) -> date:
    """Return the last day of the month for a given date."""
    if d.month == 12:
        return date(d.year + 1, 1, 1) - timedelta(days=1)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def compute_next_send(frequency: str, from_dt: datetime) -> datetime:
    """
    Calculate the next send datetime given a frequency and a reference datetime.

    Daily   → same time tomorrow
    Weekly  → same time next week (7 days)
    Monthly → same time next month (calendar month)
    """
    from apps.reports.models import FREQ_DAILY, FREQ_WEEKLY, FREQ_MONTHLY

    if frequency == FREQ_DAILY:
        return from_dt + timedelta(days=1)
    if frequency == FREQ_WEEKLY:
        return from_dt + timedelta(weeks=1)
    if frequency == FREQ_MONTHLY:
        year, month = from_dt.year, from_dt.month + 1
        if month > 12:
            month = 1
            year += 1
        return from_dt.replace(year=year, month=month)
    return from_dt + timedelta(days=1)


# ── Dispatcher ────────────────────────────────────────────────────────────────

def get_report_data(report_type: str, store, start_date: date, end_date: date) -> dict:
    """
    Central dispatcher — routes to the correct generator based on report_type.

    Returns a standardised dict:
      {
        "report_type": "sales",
        "report_name": "Sales Summary",
        "store_name": "Duka Kuu — Kariakoo",
        "date_from": "2026-05-01",
        "date_to": "2026-05-24",
        ...report-specific data...
      }

    Raises ValueError for unknown report types.
    """
    from apps.reports.models import (
        REPORT_SALES, REPORT_INVENTORY, REPORT_TAX, REPORT_CREDIT,
        REPORT_TYPE_CHOICES,
    )

    # Map type → human name
    name_map = dict(REPORT_TYPE_CHOICES)

    header = {
        "report_type": report_type,
        "report_name": name_map.get(report_type, report_type),
        "store_name":  str(store),
        "date_from":   start_date.isoformat(),
        "date_to":     end_date.isoformat(),
        "generated_at": date.today().isoformat(),
    }

    if report_type == REPORT_SALES:
        body = generate_sales_summary(store, start_date, end_date)
    elif report_type == REPORT_INVENTORY:
        body = generate_inventory_valuation(store)
    elif report_type == REPORT_TAX:
        body = generate_tax_statement(store, start_date, end_date)
    elif report_type == REPORT_CREDIT:
        body = generate_credit_aged_debtors(store)
    else:
        raise ValueError(f"Unknown report_type: {report_type!r}")

    return {**header, **body}


# ── Sales Summary ─────────────────────────────────────────────────────────────

def generate_sales_summary(store, start_date: date, end_date: date) -> dict:
    """
    Generate data for the Sales Summary report.

    Sections:
      kpis          — revenue, profit, margin_pct, transaction_count, avg_ticket
      daily_trend   — day-by-day [{date, revenue, profit, transactions}]
      top_products  — top 20 products by revenue with qty, cost, profit
      payment_mix   — [{method, amount, pct}]
      category_breakdown — revenue by product category + trend (from analytics)

    Data comes from DailySummary (fast reads) for KPIs and trend, and from
    TransactionLine for product and category breakdowns.
    """
    from apps.analytics.services import (
        get_kpi_summary, get_revenue_trend, get_payment_mix, get_top_products
    )
    from apps.analytics.services import get_sales_breakdown

    kpis          = get_kpi_summary(store, start_date, end_date)
    daily_trend   = get_revenue_trend(store, start_date, end_date)
    top_products  = get_top_products(store, start_date, end_date, limit=20)
    payment_mix   = get_payment_mix(store, start_date, end_date)
    sales_detail  = get_sales_breakdown(store, start_date, end_date)

    return {
        "kpis":                kpis,
        "daily_trend":         daily_trend,
        "top_products":        top_products,
        "payment_mix":         payment_mix,
        "category_breakdown":  sales_detail["category_breakdown"],
        "day_of_week":         sales_detail["day_of_week"],
    }


# ── Inventory Valuation ───────────────────────────────────────────────────────

def generate_inventory_valuation(store) -> dict:
    """
    Generate data for the Inventory Valuation report.

    Returns every active product with:
      - stock on hand
      - unit cost / unit price (current values from Product)
      - cost_value  = stock × unit_cost
      - retail_value = stock × unit_price
      - margin_pct = (retail_value - cost_value) / retail_value * 100

    Grouped by category, with per-category subtotals and a grand total row.

    Note: uses CURRENT Product prices, not historical transaction snapshots.
    This is correct for a stock-valuation report (you're valuing what you
    currently have at today's cost).
    """
    from apps.inventory.models import Product

    products = list(
        Product.objects
        .filter(store=store, is_active=True)
        .select_related("category")
        .order_by("category__sort_order", "category__name", "name")
        .values(
            "id", "name", "sku",
            "category__name",
            "stock", "price", "cost",
        )
    )

    # Build rows + category subtotals
    rows      = []
    cat_totals: dict[str, dict] = {}

    for p in products:
        cat   = p["category__name"] or "Uncategorised"
        cost_v  = (p["stock"] or 0) * (p["cost"]  or 0)
        retail_v = (p["stock"] or 0) * (p["price"] or 0)
        margin   = round((retail_v - cost_v) / retail_v * 100, 1) if retail_v else 0.0

        rows.append({
            "product_id":    str(p["id"]),
            "name":          p["name"],
            "sku":           p["sku"],
            "category":      cat,
            "stock":         p["stock"] or 0,
            "unit_cost":     p["cost"]  or 0,
            "unit_price":    p["price"] or 0,
            "cost_value":    cost_v,
            "retail_value":  retail_v,
            "margin_pct":    margin,
        })

        if cat not in cat_totals:
            cat_totals[cat] = {"cost_value": 0, "retail_value": 0, "sku_count": 0}
        cat_totals[cat]["cost_value"]   += cost_v
        cat_totals[cat]["retail_value"] += retail_v
        cat_totals[cat]["sku_count"]    += 1

    grand_cost   = sum(r["cost_value"]   for r in rows)
    grand_retail = sum(r["retail_value"] for r in rows)

    category_subtotals = [
        {
            "category":     cat,
            "sku_count":    data["sku_count"],
            "cost_value":   data["cost_value"],
            "retail_value": data["retail_value"],
            "margin_pct":   round(
                (data["retail_value"] - data["cost_value"]) / data["retail_value"] * 100, 1
            ) if data["retail_value"] else 0.0,
        }
        for cat, data in sorted(cat_totals.items())
    ]

    return {
        "products":           rows,
        "category_subtotals": category_subtotals,
        "totals": {
            "sku_count":    len(rows),
            "cost_value":   grand_cost,
            "retail_value": grand_retail,
            "margin_pct":   round(
                (grand_retail - grand_cost) / grand_retail * 100, 1
            ) if grand_retail else 0.0,
        },
        "valuation_date": date.today().isoformat(),
    }


# ── Tax Statement ─────────────────────────────────────────────────────────────

def generate_tax_statement(store, start_date: date, end_date: date) -> dict:
    """
    Generate data for the Tax Statement (TRA VAT) report.

    Tanzania VAT rate is 18% (TZ_VAT_RATE in settings).
    All amounts in TZS integers.

    Sections:
      summary — total gross sales, total tax collected, net (excl VAT), refunds
      daily   — day-by-day [{date, gross_sales, tax_collected, net_sales, refunds}]
      payment_breakdown — tax collected by payment method

    The tax_amount on each Transaction is the VAT component that was
    collected from the customer. This matches TRA's input-VAT reporting.

    Note: The Tax Statement covers ONLY paid transactions (status=paid).
    Credit (on-tab) transactions have not yet been cash-settled, so they
    are not included in TRA returns until payment is received.
    """
    from apps.analytics.models import DailySummary

    summaries = {
        s.date: s
        for s in DailySummary.objects.filter(
            store=store,
            date__gte=start_date,
            date__lte=end_date,
        )
    }

    daily = []
    total_gross  = 0
    total_tax    = 0
    total_refund = 0

    current = start_date
    while current <= end_date:
        s = summaries.get(current)
        gross   = s.revenue          if s else 0
        tax     = s.tax_collected    if s else 0
        refunds = s.refund_total     if s else 0
        net     = gross - tax

        total_gross  += gross
        total_tax    += tax
        total_refund += refunds

        daily.append({
            "date":         current.isoformat(),
            "label":        current.strftime("%-d %b"),
            "gross_sales":  gross,
            "tax_collected": tax,
            "net_sales":    net,    # Excl. VAT (taxable base)
            "refunds":      refunds,
        })
        current += timedelta(days=1)

    total_net = total_gross - total_tax

    from django.conf import settings
    vat_rate = getattr(settings, "TZ_VAT_RATE", 0.18)

    return {
        "vat_rate":  vat_rate,
        "summary": {
            "gross_sales":          total_gross,
            "tax_collected":        total_tax,
            "net_sales_excl_tax":   total_net,
            "refunds":              total_refund,
            "taxable_transactions": sum(1 for d in daily if d["gross_sales"] > 0),
        },
        "daily": daily,
        "note": (
            "This statement covers only paid (cash/mobile/bank) transactions. "
            "On-credit (tab) transactions are reported when payment is received."
        ),
    }


# ── Credit Aged Debtors ───────────────────────────────────────────────────────

def generate_credit_aged_debtors(store) -> dict:
    """
    Generate the Credit Aged Debtors report (accounts receivable aging).

    Aging buckets (based on days since due_date):
      Current   — not yet due (due_date in the future or today)
      1–7 d     — 1 to 7 days overdue
      8–30 d    — 8 to 30 days overdue
      31–60 d   — 31 to 60 days overdue
      60+ d     — more than 60 days overdue

    For each customer, we show the sum of open/partial tab balances per bucket.

    Returns:
      customers     — per-customer rows with balance per aging bucket
      aging_summary — total balance per bucket
      totals        — grand total outstanding, customer count, overdue count
    """
    try:
        from apps.credits.models import CreditTab
    except ImportError:
        return {
            "customers": [],
            "aging_summary": [],
            "totals": {"total": 0, "customer_count": 0, "overdue_count": 0},
        }

    today = date.today()

    # All open/partially-paid credit tabs for this store
    open_tabs = list(
        CreditTab.objects
        .filter(
            store=store,
            status__in=[CreditTab.STATUS_OPEN, CreditTab.STATUS_PARTIAL],
        )
        .select_related("customer")
        .order_by("customer__name", "due_date")
        .values(
            "id",
            "customer_id",
            "customer__name",
            "customer__phone",
            "amount",
            "amount_paid",
            "due_date",
            "created_at",
        )
    )

    def _age_key(due_date) -> str:
        """Classify a tab into an aging bucket."""
        if due_date is None:
            return "current"
        overdue_days = (today - due_date).days
        if overdue_days <= 0:
            return "current"
        if overdue_days <= 7:
            return "1_7d"
        if overdue_days <= 30:
            return "8_30d"
        if overdue_days <= 60:
            return "31_60d"
        return "60plus"

    # Aggregate per customer
    customer_data: dict = {}
    for tab in open_tabs:
        cid     = str(tab["customer_id"])
        balance = (tab["amount"] or 0) - (tab["amount_paid"] or 0)
        if balance <= 0:
            continue

        due_d = tab["due_date"]
        if hasattr(due_d, "date"):
            due_d = due_d.date()
        bucket = _age_key(due_d)

        if cid not in customer_data:
            customer_data[cid] = {
                "customer_id": cid,
                "name":        tab["customer__name"] or "Unknown",
                "phone":       tab["customer__phone"] or "",
                "total_balance": 0,
                "current": 0,
                "1_7d":   0,
                "8_30d":  0,
                "31_60d": 0,
                "60plus": 0,
                "oldest_due": None,
                "tab_count": 0,
            }

        customer_data[cid]["total_balance"] += balance
        customer_data[cid][bucket]          += balance
        customer_data[cid]["tab_count"]     += 1

        # Track the oldest due date (most urgent for follow-up)
        if due_d and (
            customer_data[cid]["oldest_due"] is None
            or (due_d < today and due_d < customer_data[cid]["oldest_due"])
        ):
            customer_data[cid]["oldest_due"] = due_d

    customers = sorted(customer_data.values(), key=lambda c: -c["total_balance"])
    for c in customers:
        if c["oldest_due"]:
            c["oldest_due"] = c["oldest_due"].isoformat()

    # Aging summary (totals per bucket)
    BUCKET_LABELS = {
        "current": "Current (not yet due)",
        "1_7d":    "1–7 days overdue",
        "8_30d":   "8–30 days overdue",
        "31_60d":  "31–60 days overdue",
        "60plus":  "60+ days overdue",
    }
    aging_summary = []
    for bucket, label in BUCKET_LABELS.items():
        total = sum(c[bucket] for c in customers)
        count = sum(1 for c in customers if c[bucket] > 0)
        aging_summary.append({
            "bucket":  bucket,
            "label":   label,
            "amount":  total,
            "count":   count,
        })

    grand_total    = sum(c["total_balance"] for c in customers)
    overdue_count  = sum(1 for c in customers if c["1_7d"] + c["8_30d"] + c["31_60d"] + c["60plus"] > 0)

    return {
        "customers": customers,
        "aging_summary": aging_summary,
        "totals": {
            "total":          grand_total,
            "customer_count": len(customers),
            "overdue_count":  overdue_count,
        },
        "as_of_date": today.isoformat(),
    }


# ── CSV Builder ───────────────────────────────────────────────────────────────

def build_csv(report_type: str, data: dict) -> tuple[str, str]:
    """
    Build a CSV string from report data.

    Returns (csv_string, filename) where filename is a safe file name
    like 'sales-summary-2026-05.csv'.

    Each report type has a custom CSV layout that matches what a Tanzanian
    shopkeeper or accountant would recognise:
      - Section headers in UPPER CASE
      - Blank lines between sections
      - Monetary values as plain integers (no currency symbol — TZS implied)
    """
    from apps.reports.models import (
        REPORT_SALES, REPORT_INVENTORY, REPORT_TAX, REPORT_CREDIT,
    )

    buf = io.StringIO()
    w   = csv.writer(buf)

    # Common header block
    w.writerow([data["report_name"].upper()])
    w.writerow([f"Store: {data['store_name']}"])
    w.writerow([f"Period: {data['date_from']}  to  {data['date_to']}"])
    w.writerow([f"Generated: {data['generated_at']}"])
    w.writerow([])

    if report_type == REPORT_SALES:
        _write_sales_csv(w, data)
    elif report_type == REPORT_INVENTORY:
        _write_inventory_csv(w, data)
    elif report_type == REPORT_TAX:
        _write_tax_csv(w, data)
    elif report_type == REPORT_CREDIT:
        _write_credit_csv(w, data)

    csv_str = buf.getvalue()
    fname   = (
        f"{report_type.replace('_','-')}-"
        f"{data['date_from'][:7]}.csv"
    )
    return csv_str, fname


def _write_sales_csv(w: csv.writer, data: dict):
    """Write Sales Summary CSV sections."""
    # KPIs
    k = data.get("kpis", {})
    w.writerow(["KPI SUMMARY"])
    w.writerow(["Revenue (TZS)", "Profit (TZS)", "Transactions", "Avg Ticket (TZS)", "Margin %"])
    w.writerow([
        k.get("revenue", 0), k.get("profit", 0),
        k.get("transaction_count", 0), k.get("avg_ticket", 0),
        k.get("margin_pct", 0),
    ])
    w.writerow([])

    # Daily trend
    w.writerow(["DAILY REVENUE"])
    w.writerow(["Date", "Label", "Revenue (TZS)", "Profit (TZS)", "Transactions"])
    for d in data.get("daily_trend", []):
        w.writerow([d["date"], d["label"], d["revenue"], d["profit"], d["transactions"]])
    w.writerow([])

    # Top products
    w.writerow(["TOP PRODUCTS"])
    w.writerow(["Product", "SKU", "Units Sold", "Revenue (TZS)", "Cost (TZS)", "Profit (TZS)"])
    for p in data.get("top_products", []):
        w.writerow([
            p["product_name"], p.get("product_sku", ""),
            p.get("qty_sold", 0), p["revenue"], p.get("cost", 0), p.get("profit", 0),
        ])
    w.writerow([])

    # Payment mix
    w.writerow(["PAYMENT MIX"])
    w.writerow(["Method", "Amount (TZS)", "Share %"])
    for m in data.get("payment_mix", []):
        w.writerow([m["method"], m["amount"], m["pct"]])
    w.writerow([])

    # Category breakdown
    w.writerow(["REVENUE BY CATEGORY"])
    w.writerow(["Category", "Revenue (TZS)", "Share %", "Trend vs Prev Period %"])
    for c in data.get("category_breakdown", []):
        w.writerow([
            c["name"], c["revenue"], c["pct"],
            c.get("trend_pct", "—"),
        ])


def _write_inventory_csv(w: csv.writer, data: dict):
    """Write Inventory Valuation CSV sections."""
    w.writerow([f"Valuation date: {data.get('valuation_date', '')}"])
    w.writerow([])

    w.writerow(["PRODUCT LIST"])
    w.writerow(["Category", "Product", "SKU", "Stock", "Unit Cost (TZS)",
                "Unit Price (TZS)", "Cost Value (TZS)", "Retail Value (TZS)", "Margin %"])
    for p in data.get("products", []):
        w.writerow([
            p["category"], p["name"], p["sku"], p["stock"],
            p["unit_cost"], p["unit_price"],
            p["cost_value"], p["retail_value"], p["margin_pct"],
        ])
    w.writerow([])

    w.writerow(["CATEGORY SUBTOTALS"])
    w.writerow(["Category", "SKUs", "Cost Value (TZS)", "Retail Value (TZS)", "Margin %"])
    for c in data.get("category_subtotals", []):
        w.writerow([
            c["category"], c["sku_count"],
            c["cost_value"], c["retail_value"], c["margin_pct"],
        ])
    w.writerow([])

    t = data.get("totals", {})
    w.writerow(["GRAND TOTAL"])
    w.writerow(["Total SKUs", "Total Cost Value (TZS)", "Total Retail Value (TZS)", "Margin %"])
    w.writerow([t.get("sku_count", 0), t.get("cost_value", 0), t.get("retail_value", 0), t.get("margin_pct", 0)])


def _write_tax_csv(w: csv.writer, data: dict):
    """Write Tax Statement CSV sections."""
    w.writerow([f"VAT Rate: {int(data.get('vat_rate', 0.18) * 100)}%"])
    w.writerow([data.get("note", "")])
    w.writerow([])

    s = data.get("summary", {})
    w.writerow(["VAT SUMMARY"])
    w.writerow(["Gross Sales (TZS)", "VAT Collected (TZS)", "Net Sales excl. VAT (TZS)",
                "Refunds (TZS)", "Taxable Days"])
    w.writerow([
        s.get("gross_sales", 0), s.get("tax_collected", 0),
        s.get("net_sales_excl_tax", 0), s.get("refunds", 0),
        s.get("taxable_transactions", 0),
    ])
    w.writerow([])

    w.writerow(["DAILY BREAKDOWN"])
    w.writerow(["Date", "Label", "Gross Sales (TZS)", "VAT Collected (TZS)",
                "Net Sales (TZS)", "Refunds (TZS)"])
    for d in data.get("daily", []):
        w.writerow([
            d["date"], d["label"],
            d["gross_sales"], d["tax_collected"],
            d["net_sales"], d["refunds"],
        ])


def _write_credit_csv(w: csv.writer, data: dict):
    """Write Credit Aged Debtors CSV sections."""
    w.writerow([f"As of: {data.get('as_of_date', '')}"])
    w.writerow([])

    w.writerow(["DEBTOR LIST"])
    w.writerow([
        "Customer", "Phone", "Total Balance (TZS)",
        "Current (TZS)", "1-7d (TZS)", "8-30d (TZS)", "31-60d (TZS)", "60+d (TZS)",
        "Oldest Due Date", "Open Tabs",
    ])
    for c in data.get("customers", []):
        w.writerow([
            c["name"], c["phone"], c["total_balance"],
            c["current"], c["1_7d"], c["8_30d"], c["31_60d"], c["60plus"],
            c.get("oldest_due", ""),
            c.get("tab_count", 0),
        ])
    w.writerow([])

    w.writerow(["AGING SUMMARY"])
    w.writerow(["Bucket", "Customers", "Amount (TZS)"])
    for b in data.get("aging_summary", []):
        w.writerow([b["label"], b["count"], b["amount"]])
    w.writerow([])

    t = data.get("totals", {})
    w.writerow(["TOTALS"])
    w.writerow(["Total Outstanding (TZS)", "Total Customers", "Overdue Customers"])
    w.writerow([t.get("total", 0), t.get("customer_count", 0), t.get("overdue_count", 0)])
