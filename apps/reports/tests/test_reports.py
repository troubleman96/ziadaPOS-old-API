"""
apps/reports/tests/test_reports.py

Tests for the reports app: report generation, CSV output, scheduled
report management, and export history.
"""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Organisation, Store, User
from apps.analytics.models import DailySummary
from apps.analytics.services import rebuild_daily_summary
from apps.credits.models import CreditTab
from apps.customers.models import Customer
from apps.inventory.models import Category, Product
from apps.reports.models import ReportExport, ScheduledReport
from apps.reports.services import (
    build_csv,
    generate_credit_aged_debtors,
    generate_inventory_valuation,
    generate_sales_summary,
    generate_tax_statement,
    get_report_data,
    parse_range_for_report,
)
from apps.transactions.models import Transaction, TransactionLine


# ── Shared fixtures ───────────────────────────────────────────────────────────

def make_base():
    """Create org, store, manager, and cashier."""
    org     = Organisation.objects.create(name="Test Org")
    store   = Store.objects.create(organisation=org, name="Duka Kuu", area="Kariakoo")
    manager = User.objects.create_user(
        username="manager1", password="pass123!", role="manager", store=store
    )
    cashier = User.objects.create_user(
        username="cashier1", password="pass123!", role="cashier", store=store
    )
    return org, store, manager, cashier


def make_transaction(store, cashier, total=50000, method="Cash", days_ago=0):
    """Create a paid transaction with a timestamp offset."""
    from django.utils import timezone
    dt = timezone.now() - timedelta(days=days_ago)
    txn = Transaction.objects.create(
        store=store,
        txn_number=f"TXN-{total}-{days_ago}-{id(store)}",
        payment_method=method,
        status=Transaction.STATUS_PAID,
        subtotal=total, total=total, tax_amount=0,
        cost_total=int(total * 0.7), profit=int(total * 0.3),
        cashier=cashier, till_number="Till #1",
    )
    Transaction.objects.filter(pk=txn.pk).update(created_at=dt)
    txn.refresh_from_db()
    return txn


def auth(client, username, password="pass123!"):
    """Authenticate an APIClient and return it."""
    resp = client.post(reverse("token_obtain_pair"), {"username": username, "password": password})
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return client


# ── parse_range_for_report ────────────────────────────────────────────────────

class ParseRangeTests(TestCase):
    """Unit tests for parse_range_for_report helper."""

    def test_30d_gives_label(self):
        """?range=30d gives a period label like '26 Apr – 25 May 2026'."""
        start, end, label = parse_range_for_report({"range": "30d"})
        self.assertIsInstance(label, str)
        self.assertGreater(len(label), 0)

    def test_explicit_dates_same_month(self):
        """Explicit dates in same month give compact label."""
        start, end, label = parse_range_for_report({
            "date_from": "2026-05-01",
            "date_to":   "2026-05-24",
        })
        self.assertEqual(start.isoformat(), "2026-05-01")
        self.assertEqual(end.isoformat(),   "2026-05-24")
        self.assertIn("May", label)

    def test_full_month_gives_month_label(self):
        """A full calendar month gives a label like 'April 2026'."""
        start, end, label = parse_range_for_report({
            "date_from": "2026-04-01",
            "date_to":   "2026-04-30",
        })
        self.assertEqual(label, "April 2026")


# ── Sales Summary ─────────────────────────────────────────────────────────────

class SalesSummaryTests(TestCase):
    """Tests for generate_sales_summary."""

    def setUp(self):
        _, self.store, self.manager, self.cashier = make_base()
        cat = Category.objects.create(name="Grocery")
        p   = Product.objects.create(
            store=self.store, category=cat, name="Unga", sku="U1",
            price=28500, cost=22000, stock=50, min_stock=10, max_stock=100,
        )
        for i in range(3):
            txn = make_transaction(self.store, self.cashier, total=100000, days_ago=i)
            TransactionLine.objects.create(
                transaction=txn, product=p, product_name=p.name, product_sku=p.sku,
                unit_price=p.price, unit_cost=p.cost, qty=2,
            )
            rebuild_daily_summary(self.store, date.today() - timedelta(days=i))

    def test_sales_summary_has_all_sections(self):
        """generate_sales_summary returns kpis, daily_trend, top_products, payment_mix."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = generate_sales_summary(self.store, start, end)
        for key in ["kpis", "daily_trend", "top_products", "payment_mix"]:
            self.assertIn(key, result)

    def test_daily_trend_length(self):
        """daily_trend has one entry per day in the range."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = generate_sales_summary(self.store, start, end)
        self.assertEqual(len(result["daily_trend"]), 7)

    def test_top_products_includes_unga(self):
        """Top products includes our test product."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = generate_sales_summary(self.store, start, end)
        names = [p["product_name"] for p in result["top_products"]]
        self.assertIn("Unga", names)


# ── Inventory Valuation ───────────────────────────────────────────────────────

class InventoryValuationTests(TestCase):
    """Tests for generate_inventory_valuation."""

    def setUp(self):
        _, self.store, self.manager, self.cashier = make_base()
        cat = Category.objects.create(name="Grocery")
        Product.objects.create(
            store=self.store, category=cat, name="Unga", sku="U1",
            price=28500, cost=22000, stock=50, min_stock=10, max_stock=100,
        )
        Product.objects.create(
            store=self.store, category=cat, name="Sukari", sku="S1",
            price=7000, cost=5500, stock=80, min_stock=20, max_stock=200,
        )

    def test_valuation_has_products(self):
        """Returns a list of products with cost and retail values."""
        result = generate_inventory_valuation(self.store)
        self.assertEqual(len(result["products"]), 2)

    def test_cost_value_calculation(self):
        """cost_value = stock × unit_cost."""
        result = generate_inventory_valuation(self.store)
        for p in result["products"]:
            expected = p["stock"] * p["unit_cost"]
            self.assertEqual(p["cost_value"], expected)

    def test_grand_total_matches_sum(self):
        """Grand total cost_value equals sum of product cost values."""
        result = generate_inventory_valuation(self.store)
        expected_total = sum(p["cost_value"] for p in result["products"])
        self.assertEqual(result["totals"]["cost_value"], expected_total)

    def test_inactive_products_excluded(self):
        """Soft-deleted products are not included in valuation."""
        Product.objects.filter(store=self.store).update(is_active=False)
        result = generate_inventory_valuation(self.store)
        self.assertEqual(len(result["products"]), 0)


# ── Tax Statement ─────────────────────────────────────────────────────────────

class TaxStatementTests(TestCase):
    """Tests for generate_tax_statement."""

    def setUp(self):
        _, self.store, self.manager, self.cashier = make_base()
        # Create transaction with tax
        from django.utils import timezone
        dt = timezone.now()
        txn = Transaction.objects.create(
            store=self.store,
            txn_number="TXN-TAX-001",
            payment_method="Cash",
            status=Transaction.STATUS_PAID,
            subtotal=100000, total=118000,
            tax_amount=18000, cost_total=70000, profit=30000,
            cashier=self.cashier, till_number="Till #1",
        )
        rebuild_daily_summary(self.store, date.today())

    def test_tax_statement_has_sections(self):
        """Tax statement returns summary and daily sections."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = generate_tax_statement(self.store, start, end)
        for key in ["summary", "daily", "vat_rate"]:
            self.assertIn(key, result)

    def test_daily_length(self):
        """daily array has 7 entries for a 7-day range."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = generate_tax_statement(self.store, start, end)
        self.assertEqual(len(result["daily"]), 7)

    def test_vat_rate_is_18pct(self):
        """VAT rate is 18%."""
        start = date.today() - timedelta(days=6)
        end   = date.today()
        result = generate_tax_statement(self.store, start, end)
        self.assertAlmostEqual(result["vat_rate"], 0.18)


# ── Credit Aged Debtors ───────────────────────────────────────────────────────

class CreditAgedDebtorsTests(TestCase):
    """Tests for generate_credit_aged_debtors."""

    def setUp(self):
        _, self.store, self.manager, self.cashier = make_base()
        self.customer = Customer.objects.create(
            store=self.store, name="Fatuma Ally", phone="0712345678",
        )
        # Create an open credit tab
        from django.utils import timezone
        CreditTab.objects.create(
            store=self.store,
            customer=self.customer,
            cashier=self.cashier,
            amount=50000,
            amount_paid=0,
            status=CreditTab.STATUS_OPEN,
            due_date=date.today() + timedelta(days=14),
        )

    def test_aged_debtors_has_sections(self):
        """Returns customers, aging_summary, and totals."""
        result = generate_credit_aged_debtors(self.store)
        for key in ["customers", "aging_summary", "totals"]:
            self.assertIn(key, result)

    def test_customer_appears_in_report(self):
        """Our customer with an open tab appears in the debtor list."""
        result = generate_credit_aged_debtors(self.store)
        names = [c["name"] for c in result["customers"]]
        self.assertIn("Fatuma Ally", names)

    def test_current_bucket_for_future_due_date(self):
        """Tab with future due date falls in 'current' bucket."""
        result = generate_credit_aged_debtors(self.store)
        customer_row = next(
            c for c in result["customers"] if c["name"] == "Fatuma Ally"
        )
        self.assertEqual(customer_row["current"], 50000)
        self.assertEqual(customer_row["1_7d"], 0)

    def test_overdue_tab_in_correct_bucket(self):
        """Tab with past due date appears in an overdue bucket."""
        CreditTab.objects.create(
            store=self.store, customer=self.customer,
            cashier=self.cashier,
            amount=30000, amount_paid=0,
            status=CreditTab.STATUS_OPEN,
            due_date=date.today() - timedelta(days=20),  # 20 days overdue → 8-30d
        )
        result = generate_credit_aged_debtors(self.store)
        row = next(c for c in result["customers"] if c["name"] == "Fatuma Ally")
        self.assertEqual(row["8_30d"], 30000)

    def test_totals_match_customer_sum(self):
        """Grand total = sum of all customer balances."""
        result = generate_credit_aged_debtors(self.store)
        expected = sum(c["total_balance"] for c in result["customers"])
        self.assertEqual(result["totals"]["total"], expected)


# ── CSV Builder ───────────────────────────────────────────────────────────────

class CSVBuilderTests(TestCase):
    """Tests for build_csv output format."""

    def setUp(self):
        _, self.store, self.manager, self.cashier = make_base()
        cat = Category.objects.create(name="Grocery")
        Product.objects.create(
            store=self.store, category=cat, name="Unga", sku="U1",
            price=28500, cost=22000, stock=50, min_stock=10, max_stock=100,
        )

    def test_sales_csv_contains_headers(self):
        """Sales CSV output has 'KPI SUMMARY' section header."""
        data = get_report_data(
            "sales", self.store,
            date.today() - timedelta(days=6), date.today()
        )
        csv_str, fname = build_csv("sales", data)
        self.assertIn("KPI SUMMARY", csv_str)
        self.assertTrue(fname.startswith("sales-"))
        self.assertTrue(fname.endswith(".csv"))

    def test_inventory_csv_contains_product(self):
        """Inventory CSV contains the product name."""
        data = get_report_data(
            "inventory", self.store,
            date.today(), date.today()
        )
        csv_str, fname = build_csv("inventory", data)
        self.assertIn("Unga", csv_str)
        self.assertIn("PRODUCT LIST", csv_str)

    def test_tax_csv_contains_vat_section(self):
        """Tax CSV has VAT SUMMARY header."""
        data = get_report_data(
            "tax", self.store,
            date.today() - timedelta(days=6), date.today()
        )
        csv_str, fname = build_csv("tax", data)
        self.assertIn("VAT SUMMARY", csv_str)


# ── Generate Report API ───────────────────────────────────────────────────────

class GenerateReportAPITests(TestCase):
    """Tests for POST /api/v1/reports/generate/."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.manager, self.cashier = make_base()
        auth(self.client, "cashier1")

        cat = Category.objects.create(name="Grocery")
        Product.objects.create(
            store=self.store, category=cat, name="Unga", sku="U1",
            price=28500, cost=22000, stock=50, min_stock=10, max_stock=100,
        )
        for i in range(3):
            make_transaction(self.store, self.cashier, total=50000, days_ago=i)
            rebuild_daily_summary(self.store, date.today() - timedelta(days=i))

    def test_generate_csv_returns_file(self):
        """Generating a sales CSV returns text/csv content type."""
        resp = self.client.post(
            reverse("reports-generate"),
            {"report_type": "sales", "format": "csv", "range": "7d"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("attachment", resp.get("Content-Disposition", ""))

    def test_generate_json_returns_envelope(self):
        """Generating a JSON report returns the standard API envelope."""
        resp = self.client.post(
            reverse("reports-generate"),
            {"report_type": "sales", "format": "json", "range": "7d"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("report", resp.data["data"])

    def test_generate_creates_export_record(self):
        """Generating a report creates a ReportExport audit record."""
        before = ReportExport.objects.count()
        self.client.post(
            reverse("reports-generate"),
            {"report_type": "sales", "format": "csv", "range": "7d"},
            format="json",
        )
        self.assertEqual(ReportExport.objects.count(), before + 1)

    def test_invalid_report_type_rejected(self):
        """Unknown report type returns 400."""
        resp = self.client.post(
            reverse("reports-generate"),
            {"report_type": "invalid_type", "format": "csv"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_inventory_report_no_date_range_required(self):
        """Inventory valuation works without a date range."""
        resp = self.client.post(
            reverse("reports-generate"),
            {"report_type": "inventory", "format": "csv"},
            format="json",
        )
        self.assertIn(resp.status_code, [200, 201])

    def test_unauthenticated_denied(self):
        """Unauthenticated request is rejected with 401."""
        client = APIClient()
        resp = client.post(
            reverse("reports-generate"),
            {"report_type": "sales", "format": "csv"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Scheduled Reports API ─────────────────────────────────────────────────────

class ScheduledReportAPITests(TestCase):
    """Tests for scheduled report CRUD endpoints."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.manager, self.cashier = make_base()

    def test_manager_can_create_scheduled_report(self):
        """Store manager can POST to /reports/scheduled/."""
        auth(self.client, "manager1")
        resp = self.client.post(
            reverse("reports-scheduled"),
            {
                "report_type":       "sales",
                "name":              "Daily Sales",
                "frequency":         "daily",
                "date_range_preset": "7d",
                "recipients":        ["manager@store.co.tz"],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ScheduledReport.objects.count(), 1)

    def test_cashier_cannot_create_scheduled_report(self):
        """Cashier does not have permission to create scheduled reports."""
        auth(self.client, "cashier1")
        resp = self.client.post(
            reverse("reports-scheduled"),
            {
                "report_type": "sales", "name": "X",
                "frequency": "daily", "date_range_preset": "7d",
                "recipients": ["x@x.com"],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_scheduled_reports(self):
        """GET /reports/scheduled/ returns the list."""
        auth(self.client, "cashier1")
        ScheduledReport.objects.create(
            store=self.store, organisation=self.store.organisation,
            report_type="sales", name="Test", frequency="daily",
            date_range_preset="7d", recipients=["t@t.com"],
        )
        resp = self.client.get(reverse("reports-scheduled"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["data"]["scheduled_reports"]), 1)

    def test_toggle_enabled(self):
        """PATCH /reports/scheduled/{id}/ can toggle is_enabled."""
        auth(self.client, "manager1")
        s = ScheduledReport.objects.create(
            store=self.store, organisation=self.store.organisation,
            report_type="sales", name="Test", frequency="daily",
            date_range_preset="7d", recipients=["t@t.com"],
            is_enabled=True,
        )
        resp = self.client.patch(
            reverse("reports-scheduled-detail", args=[s.id]),
            {"is_enabled": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        s.refresh_from_db()
        self.assertFalse(s.is_enabled)

    def test_delete_scheduled_report(self):
        """DELETE /reports/scheduled/{id}/ removes the record."""
        auth(self.client, "manager1")
        s = ScheduledReport.objects.create(
            store=self.store, organisation=self.store.organisation,
            report_type="sales", name="Test", frequency="daily",
            date_range_preset="7d", recipients=["t@t.com"],
        )
        resp = self.client.delete(
            reverse("reports-scheduled-detail", args=[s.id])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ScheduledReport.objects.count(), 0)


# ── Export History ────────────────────────────────────────────────────────────

class ExportHistoryTests(TestCase):
    """Tests for the export history endpoint."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.manager, self.cashier = make_base()
        auth(self.client, "cashier1")

        # Seed some export records
        for i in range(3):
            ReportExport.objects.create(
                store=self.store,
                organisation=self.store.organisation,
                created_by=self.cashier,
                report_type="sales",
                name="Sales Summary",
                period_label="May 2026",
                date_from=date.today() - timedelta(days=30),
                date_to=date.today(),
                format="csv",
                file_size_bytes=50000,
            )

    def test_history_returns_list(self):
        """GET /reports/exports/ returns export history rows."""
        resp = self.client.get(reverse("reports-exports"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["data"]["exports"]), 3)

    def test_history_filter_by_type(self):
        """?report_type=inventory returns only inventory exports."""
        ReportExport.objects.create(
            store=self.store,
            organisation=self.store.organisation,
            report_type="inventory",
            name="Inventory Valuation",
            period_label="25 May 2026",
            date_from=date.today(), date_to=date.today(),
            format="csv", file_size_bytes=90000,
        )
        resp = self.client.get(reverse("reports-exports") + "?report_type=inventory")
        exports = resp.data["data"]["exports"]
        self.assertEqual(len(exports), 1)
        self.assertEqual(exports[0]["report_type"], "inventory")
