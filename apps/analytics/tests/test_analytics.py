"""
apps/analytics/tests/test_analytics.py

Tests for the analytics app:
  - DailySummary rebuild service
  - Revenue trend, payment mix, top products, KPI summary
  - Sales breakdown (category, DOW, hourly)
  - Product performance table
  - Customer analytics (visits, segments, cohorts, top customers)
  - Cashflow
  - Dashboard endpoint
"""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Organisation, Store, User
from apps.analytics.models import DailySummary
from apps.analytics.services import (
    get_cashflow,
    get_customer_analytics,
    get_dashboard_data,
    get_kpi_summary,
    get_payment_mix,
    get_product_performance,
    get_revenue_trend,
    get_sales_breakdown,
    get_top_products,
    rebuild_daily_summary,
)
from apps.customers.models import Customer
from apps.inventory.models import Category, Product
from apps.transactions.models import Transaction, TransactionLine


# ── Shared helpers ────────────────────────────────────────────────────────────

def make_base_fixtures():
    """Create org, store, and cashier user."""
    org     = Organisation.objects.create(name="Test Org")
    store   = Store.objects.create(organisation=org, name="Main Store", area="Kariakoo")
    cashier = User.objects.create_user(
        username="cashier1", password="pass123!", role="cashier", store=store
    )
    return org, store, cashier


def make_transaction(store, cashier, method="Cash", total=50000, date_offset=0,
                     customer=None, status=None):
    """Create a test transaction on a specific day."""
    from django.utils import timezone

    txn_status = status or Transaction.STATUS_PAID
    dt = timezone.now() - timedelta(days=date_offset)
    txn = Transaction.objects.create(
        store=store,
        txn_number=f"TXN-TEST-{total}-{date_offset}-{id(store)}",
        payment_method=method,
        status=txn_status,
        subtotal=total,
        total=total,
        tax_amount=0,
        cost_total=int(total * 0.7),
        profit=int(total * 0.3),
        cashier=cashier,
        till_number="Till #1",
        customer=customer,
        customer_name=customer.name if customer else "Walk-in",
    )
    # Override created_at (auto_now_add doesn't allow direct set)
    Transaction.objects.filter(pk=txn.pk).update(created_at=dt)
    txn.refresh_from_db()
    return txn


def auth(client, username, password="pass123!"):
    """Authenticate an APIClient."""
    resp = client.post(reverse("token_obtain_pair"), {"username": username, "password": password})
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return client


# ── DailySummary Rebuild ──────────────────────────────────────────────────────

class RebuildDailySummaryTests(TestCase):
    """Test the rebuild_daily_summary service function."""

    def setUp(self):
        _, self.store, self.cashier = make_base_fixtures()

    def test_creates_summary_for_day(self):
        """rebuild_daily_summary creates a DailySummary row."""
        make_transaction(self.store, self.cashier, total=100000, date_offset=0)
        today = date.today()
        summary = rebuild_daily_summary(self.store, today)
        self.assertIsNotNone(summary)
        self.assertEqual(summary.store, self.store)
        self.assertEqual(summary.date, today)

    def test_summary_revenue_matches_transactions(self):
        """Revenue in summary = sum of paid transaction totals."""
        make_transaction(self.store, self.cashier, method="Cash",   total=30000, date_offset=0)
        make_transaction(self.store, self.cashier, method="M-Pesa", total=20000, date_offset=0)
        today = date.today()
        summary = rebuild_daily_summary(self.store, today)
        self.assertEqual(summary.revenue, 50000)

    def test_rebuild_is_idempotent(self):
        """Calling rebuild multiple times for same day gives same result."""
        make_transaction(self.store, self.cashier, total=40000, date_offset=0)
        today = date.today()
        s1 = rebuild_daily_summary(self.store, today)
        s2 = rebuild_daily_summary(self.store, today)
        self.assertEqual(s1.pk, s2.pk)
        self.assertEqual(s1.revenue, s2.revenue)

    def test_zero_day_has_zero_revenue(self):
        """Day with no transactions has zero revenue summary."""
        yesterday = date.today() - timedelta(days=1)
        summary = rebuild_daily_summary(self.store, yesterday)
        self.assertEqual(summary.revenue, 0)
        self.assertEqual(summary.transaction_count, 0)


# ── Revenue / KPI API ─────────────────────────────────────────────────────────

class RevenueAPITests(TestCase):
    """Test core analytics API endpoints."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.cashier = make_base_fixtures()
        auth(self.client, "cashier1")

        # Build 7 days of data
        today = date.today()
        for i in range(7):
            make_transaction(self.store, self.cashier, total=100000, date_offset=i)
            rebuild_daily_summary(self.store, today - timedelta(days=i))

    def test_overview_returns_all_sections(self):
        """GET /analytics/overview/ returns kpis, trend, payment_mix."""
        resp = self.client.get(reverse("analytics-overview") + "?range=7d")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertIn("kpis", data)
        self.assertIn("trend", data)
        self.assertIn("payment_mix", data)

    def test_trend_length_matches_range(self):
        """?range=7d returns exactly 7 trend data points."""
        resp = self.client.get(reverse("analytics-trend") + "?range=7d")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        trend = resp.data["data"]["trend"]
        self.assertEqual(len(trend), 7)

    def test_summary_endpoint(self):
        """GET /analytics/summary/ returns revenue and transaction_count."""
        resp = self.client.get(reverse("analytics-summary") + "?range=7d")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertIn("revenue", data)
        self.assertIn("transaction_count", data)

    def test_payment_mix_endpoint(self):
        """GET /analytics/payment-mix/ returns Cash in the mix."""
        resp = self.client.get(reverse("analytics-payment-mix") + "?range=7d")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mix = resp.data["data"]["payment_mix"]
        self.assertIsInstance(mix, list)
        methods = [m["method"] for m in mix]
        self.assertIn("Cash", methods)

    def test_unauthenticated_denied(self):
        """Unauthenticated request is rejected."""
        client = APIClient()
        resp = client.get(reverse("analytics-overview"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Top Products ──────────────────────────────────────────────────────────────

class TopProductsTests(TestCase):
    """Test the top-products endpoint."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.cashier = make_base_fixtures()
        auth(self.client, "cashier1")

        cat = Category.objects.create(name="Grocery")
        self.p1 = Product.objects.create(
            store=self.store, category=cat, name="Unga wa Sembe", sku="UNG-001",
            price=28500, cost=22000, stock=50, min_stock=10, max_stock=100,
        )
        self.p2 = Product.objects.create(
            store=self.store, category=cat, name="Sukari", sku="SUK-001",
            price=7000, cost=5400, stock=60, min_stock=20, max_stock=100,
        )

        txn = make_transaction(self.store, self.cashier, total=63000, date_offset=0)
        TransactionLine.objects.create(
            transaction=txn, product=self.p1,
            product_name=self.p1.name, product_sku=self.p1.sku,
            unit_price=self.p1.price, unit_cost=self.p1.cost, qty=2,
        )
        TransactionLine.objects.create(
            transaction=txn, product=self.p2,
            product_name=self.p2.name, product_sku=self.p2.sku,
            unit_price=self.p2.price, unit_cost=self.p2.cost, qty=1,
        )

    def test_top_products_returns_list(self):
        """GET /analytics/top-products/ returns a list."""
        resp = self.client.get(reverse("analytics-top-products") + "?range=7d")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        products = resp.data["data"]["top_products"]
        self.assertIsInstance(products, list)

    def test_top_products_sorted_by_revenue(self):
        """Products are sorted by revenue descending (Unga > Sukari)."""
        resp = self.client.get(reverse("analytics-top-products") + "?range=7d")
        products = resp.data["data"]["top_products"]
        if len(products) > 1:
            self.assertGreaterEqual(products[0]["revenue"], products[1]["revenue"])


# ── DailySummary Model ────────────────────────────────────────────────────────

class DailySummaryModelTests(TestCase):
    """Unit tests for DailySummary model properties."""

    def setUp(self):
        _, self.store, _ = make_base_fixtures()

    def test_margin_pct_computed_correctly(self):
        """margin_pct = profit / (revenue + credit_revenue) * 100."""
        s = DailySummary.objects.create(
            store=self.store, date=date.today(),
            revenue=100000, credit_revenue=0, profit=22000,
        )
        self.assertAlmostEqual(s.margin_pct, 22.0)

    def test_avg_ticket_computed_correctly(self):
        """avg_ticket = total revenue / transaction_count."""
        s = DailySummary.objects.create(
            store=self.store, date=date.today(),
            revenue=100000, credit_revenue=0, transaction_count=4,
        )
        self.assertEqual(s.avg_ticket, 25000)

    def test_margin_pct_zero_when_no_revenue(self):
        """margin_pct returns 0.0 when revenue is 0."""
        s = DailySummary.objects.create(
            store=self.store, date=date.today(), revenue=0, profit=0,
        )
        self.assertEqual(s.margin_pct, 0.0)


# ── Sales Breakdown ───────────────────────────────────────────────────────────

class SalesBreakdownTests(TestCase):
    """Tests for GET /analytics/sales/ and get_sales_breakdown service."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.cashier = make_base_fixtures()
        auth(self.client, "cashier1")

        # Create categories + products + transactions with lines
        cat_g = Category.objects.create(name="Grocery")
        cat_b = Category.objects.create(name="Beverage")
        self.p1 = Product.objects.create(
            store=self.store, category=cat_g, name="Unga", sku="P1",
            price=28500, cost=22000, stock=50, min_stock=10, max_stock=100,
        )
        self.p2 = Product.objects.create(
            store=self.store, category=cat_b, name="Juice", sku="P2",
            price=5000, cost=3000, stock=80, min_stock=20, max_stock=200,
        )

        for i in range(7):
            txn = make_transaction(self.store, self.cashier, total=100000, date_offset=i)
            TransactionLine.objects.create(
                transaction=txn, product=self.p1,
                product_name=self.p1.name, product_sku=self.p1.sku,
                unit_price=self.p1.price, unit_cost=self.p1.cost, qty=2,
            )
            TransactionLine.objects.create(
                transaction=txn, product=self.p2,
                product_name=self.p2.name, product_sku=self.p2.sku,
                unit_price=self.p2.price, unit_cost=self.p2.cost, qty=3,
            )
            rebuild_daily_summary(self.store, date.today() - timedelta(days=i))

    def test_sales_endpoint_returns_200(self):
        """GET /analytics/sales/ returns 200 with required sections."""
        resp = self.client.get(reverse("analytics-sales") + "?range=7d")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertIn("category_breakdown", data)
        self.assertIn("day_of_week", data)
        self.assertIn("hourly_pattern", data)
        self.assertIn("kpis", data)
        self.assertIn("trend", data)

    def test_category_breakdown_has_two_categories(self):
        """Both Grocery and Beverage appear in category breakdown."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_sales_breakdown(self.store, start, end)
        names = [c["name"] for c in result["category_breakdown"]]
        self.assertIn("Grocery",  names)
        self.assertIn("Beverage", names)

    def test_hourly_pattern_has_14_slots(self):
        """Hourly pattern covers 07:00–20:00 (14 slots)."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_sales_breakdown(self.store, start, end)
        self.assertEqual(len(result["hourly_pattern"]), 14)

    def test_day_of_week_has_7_entries(self):
        """Day-of-week always has 7 entries (Mon–Sun)."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_sales_breakdown(self.store, start, end)
        self.assertEqual(len(result["day_of_week"]), 7)

    def test_category_pcts_sum_to_100(self):
        """Category revenue percentages add up to ~100."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_sales_breakdown(self.store, start, end)
        total_pct = sum(c["pct"] for c in result["category_breakdown"])
        self.assertAlmostEqual(total_pct, 100.0, delta=1.0)


# ── Product Performance ───────────────────────────────────────────────────────

class ProductPerformanceTests(TestCase):
    """Tests for GET /analytics/products/ and get_product_performance service."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.cashier = make_base_fixtures()
        auth(self.client, "cashier1")

        cat_g = Category.objects.create(name="Grocery")
        cat_b = Category.objects.create(name="Beverage")
        self.p1 = Product.objects.create(
            store=self.store, category=cat_g, name="Unga", sku="P1",
            price=28500, cost=22000, stock=50, min_stock=10, max_stock=100,
        )
        self.p2 = Product.objects.create(
            store=self.store, category=cat_b, name="Juice", sku="P2",
            price=5000, cost=3000, stock=80, min_stock=20, max_stock=200,
        )

        txn = make_transaction(self.store, self.cashier, total=72000, date_offset=0)
        TransactionLine.objects.create(
            transaction=txn, product=self.p1,
            product_name=self.p1.name, product_sku=self.p1.sku,
            unit_price=self.p1.price, unit_cost=self.p1.cost, qty=2,
        )
        TransactionLine.objects.create(
            transaction=txn, product=self.p2,
            product_name=self.p2.name, product_sku=self.p2.sku,
            unit_price=self.p2.price, unit_cost=self.p2.cost, qty=3,
        )

    def test_products_endpoint_returns_200(self):
        """GET /analytics/products/ returns 200 with totals and products list."""
        resp = self.client.get(reverse("analytics-products") + "?range=7d")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertIn("products", data)
        self.assertIn("totals", data)

    def test_products_have_required_fields(self):
        """Each product row has margin_pct, trend_pct, revenue_share_pct, category."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        products = get_product_performance(self.store, start, end)
        self.assertGreater(len(products), 0)
        p = products[0]
        for field in ["product_name", "category", "units_sold", "revenue",
                      "cost", "profit", "margin_pct", "revenue_share_pct"]:
            self.assertIn(field, p)

    def test_category_filter_works(self):
        """?category=Grocery returns only Grocery products."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        products = get_product_performance(self.store, start, end, category="Grocery")
        for p in products:
            self.assertEqual(p["category"], "Grocery")

    def test_category_filter_excludes_others(self):
        """?category=Grocery does not include Beverage products."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        products = get_product_performance(self.store, start, end, category="Grocery")
        names = [p["product_name"] for p in products]
        self.assertNotIn("Juice", names)

    def test_margin_calculation(self):
        """margin_pct = (revenue - cost) / revenue * 100."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        products = get_product_performance(self.store, start, end)
        for p in products:
            if p["revenue"] > 0:
                expected = round((p["revenue"] - p["cost"]) / p["revenue"] * 100, 1)
                self.assertAlmostEqual(p["margin_pct"], expected, delta=0.1)

    def test_products_sorted_endpoint_sort_param(self):
        """?sort=units sorts by units_sold descending."""
        resp = self.client.get(reverse("analytics-products") + "?range=7d&sort=units")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        products = resp.data["data"]["products"]
        if len(products) > 1:
            self.assertGreaterEqual(products[0]["units_sold"], products[1]["units_sold"])


# ── Customer Analytics ────────────────────────────────────────────────────────

class CustomerAnalyticsTests(TestCase):
    """Tests for GET /analytics/customers/ and get_customer_analytics service."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.cashier = make_base_fixtures()
        auth(self.client, "cashier1")

        # Create two customers
        self.c1 = Customer.objects.create(
            store=self.store, name="Fatuma Ally", phone="0712345678",
            segment=Customer.SEGMENT_VIP,
        )
        self.c2 = Customer.objects.create(
            store=self.store, name="Hassan Bakari", phone="0712345679",
            segment=Customer.SEGMENT_REGULAR,
        )

        # c1 transacted 3 days ago (should be "returning" in last 7d)
        # c2 transacted today (should be "new" in last 7d if no prior transaction)
        make_transaction(self.store, self.cashier, total=80000, date_offset=3,
                         customer=self.c1)
        make_transaction(self.store, self.cashier, total=50000, date_offset=0,
                         customer=self.c2)

    def test_customers_endpoint_returns_200(self):
        """GET /analytics/customers/ returns 200 with all required sections."""
        resp = self.client.get(reverse("analytics-customers") + "?range=7d")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertIn("daily_visits", data)
        self.assertIn("segments", data)
        self.assertIn("retention_cohorts", data)
        self.assertIn("top_customers", data)
        self.assertIn("kpis", data)

    def test_daily_visits_length_matches_range(self):
        """daily_visits has one entry per day in the range."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_customer_analytics(self.store, start, end)
        self.assertEqual(len(result["daily_visits"]), 7)

    def test_top_customers_sorted_by_spend(self):
        """top_customers are sorted by spent descending."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_customer_analytics(self.store, start, end)
        top = result["top_customers"]
        if len(top) > 1:
            self.assertGreaterEqual(top[0]["spent"], top[1]["spent"])

    def test_top_customers_have_required_fields(self):
        """Each top customer row has name, visits, spent, avg_ticket, avatar_hue."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_customer_analytics(self.store, start, end)
        for c in result["top_customers"]:
            for field in ["customer_id", "name", "visits", "spent", "avg_ticket"]:
                self.assertIn(field, c)

    def test_segments_present(self):
        """Segments returned include VIP and Regular."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_customer_analytics(self.store, start, end)
        seg_names = [s["segment"] for s in result["segments"]]
        # At least one of our segments should appear
        self.assertTrue(
            any(s in seg_names for s in [Customer.SEGMENT_VIP, Customer.SEGMENT_REGULAR])
        )

    def test_retention_cohorts_has_4_entries(self):
        """retention_cohorts always returns last 4 months."""
        start = date.today() - timedelta(days=29)
        end   = date.today()
        result = get_customer_analytics(self.store, start, end)
        self.assertEqual(len(result["retention_cohorts"]), 4)


# ── Cashflow ──────────────────────────────────────────────────────────────────

class CashflowTests(TestCase):
    """Tests for GET /analytics/cashflow/ and get_cashflow service."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.cashier = make_base_fixtures()
        auth(self.client, "cashier1")

        for i in range(7):
            make_transaction(self.store, self.cashier, total=100000, date_offset=i)
            rebuild_daily_summary(self.store, date.today() - timedelta(days=i))

    def test_cashflow_endpoint_returns_200(self):
        """GET /analytics/cashflow/ returns 200 with all sections."""
        resp = self.client.get(reverse("analytics-cashflow") + "?range=7d")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertIn("totals", data)
        self.assertIn("daily", data)
        self.assertIn("running_balance", data)
        self.assertIn("expense_breakdown", data)
        self.assertIn("payment_inflow", data)
        self.assertIn("credit_outstanding", data)

    def test_cashflow_totals_fields(self):
        """Cashflow totals includes inflow, cogs, opex, net."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_cashflow(self.store, start, end)
        totals = result["totals"]
        for field in ["inflow", "cogs", "opex", "net", "net_margin_pct"]:
            self.assertIn(field, totals)

    def test_daily_cashflow_length_matches_range(self):
        """daily array has one entry per day in the range."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_cashflow(self.store, start, end)
        self.assertEqual(len(result["daily"]), 7)

    def test_running_balance_length_matches_daily(self):
        """running_balance has same length as daily."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_cashflow(self.store, start, end)
        self.assertEqual(len(result["running_balance"]), len(result["daily"]))

    def test_net_equals_inflow_minus_cogs(self):
        """Without OPEX, net = inflow - COGS."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_cashflow(self.store, start, end)
        for day in result["daily"]:
            self.assertEqual(day["net"], day["inflow"] - day["cogs"])

    def test_expense_breakdown_has_cogs(self):
        """Expense breakdown contains Cost of Goods row."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = get_cashflow(self.store, start, end)
        names = [e["name"] for e in result["expense_breakdown"]]
        self.assertIn("Cost of Goods", names)


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardTests(TestCase):
    """Tests for GET /analytics/dashboard/."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.cashier = make_base_fixtures()
        auth(self.client, "cashier1")

        # Today's transaction
        make_transaction(self.store, self.cashier, total=150000, date_offset=0)
        rebuild_daily_summary(self.store, date.today())

        # Low stock product
        cat = Category.objects.create(name="Grocery")
        Product.objects.create(
            store=self.store, category=cat, name="Low Product", sku="LOW-001",
            price=10000, cost=7000, stock=3, min_stock=10, max_stock=50,
        )

    def test_dashboard_endpoint_returns_200(self):
        """GET /analytics/dashboard/ returns 200."""
        resp = self.client.get(reverse("analytics-dashboard"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_dashboard_has_all_widgets(self):
        """Dashboard response contains all expected widget sections."""
        resp = self.client.get(reverse("analytics-dashboard"))
        data = resp.data["data"]
        self.assertIn("kpis_today",   data)
        self.assertIn("hourly_today", data)
        self.assertIn("payment_mix",  data)
        self.assertIn("top_products", data)
        self.assertIn("low_stock",    data)
        self.assertIn("credit_kpi",   data)

    def test_hourly_today_has_14_slots(self):
        """hourly_today covers 07:00–20:00 (14 slots)."""
        resp = self.client.get(reverse("analytics-dashboard"))
        hourly = resp.data["data"]["hourly_today"]
        self.assertEqual(len(hourly), 14)

    def test_low_stock_shows_product_below_min(self):
        """low_stock includes products at or below min_stock."""
        resp = self.client.get(reverse("analytics-dashboard"))
        low = resp.data["data"]["low_stock"]
        names = [p["name"] for p in low]
        self.assertIn("Low Product", names)
