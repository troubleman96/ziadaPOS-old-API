"""
apps/transactions/tests/test_transactions.py

Tests for transactions: POS checkout, list, detail, refund.
"""

from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Organisation, Store, User
from apps.inventory.models import Category, Product
from apps.transactions.models import Transaction, TransactionLine


def make_base_fixtures():
    """Create shared fixtures: org, store, category, user."""
    org   = Organisation.objects.create(name="Test Org")
    store = Store.objects.create(organisation=org, name="Main", area="Kariakoo")
    cat   = Category.objects.create(name="Grocery")
    user  = User.objects.create_user(
        username="cashier1", password="pass123!", role="cashier", store=store
    )
    return org, store, cat, user


def make_product(store, cat, name="Unga", sku="UWS-001", price=28500, cost=22000, stock=50):
    return Product.objects.create(
        store=store, category=cat, name=name, sku=sku,
        price=price, cost=cost, stock=stock, min_stock=10, max_stock=100,
    )


class CompleteSaleTests(TestCase):
    """Test the POS complete-sale endpoint."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.cat, self.user = make_base_fixtures()
        self.product = make_product(self.store, self.cat)
        # Authenticate as cashier
        resp = self.client.post(reverse("token_obtain_pair"),
                                {"username": "cashier1", "password": "pass123!"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_complete_cash_sale(self):
        """POST /complete-sale/ with Cash creates a paid transaction."""
        resp = self.client.post(reverse("complete-sale"), {
            "items": [{"product_id": str(self.product.id), "qty": 2}],
            "payment_method": "Cash",
            "till_number": "Till #1",
        }, format="json")

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.data["data"]
        self.assertEqual(data["status"], "paid")
        self.assertEqual(data["payment_method"], "Cash")
        # 2 × 28500 = 57000 subtotal, no discount
        # tax = 57000 × 0.18 = 10260
        # total = 57000 + 10260 = 67260
        self.assertEqual(data["subtotal"], 57000)
        self.assertEqual(data["total"], 67260)
        # Lines should be created
        self.assertEqual(len(data["lines"]), 1)
        self.assertEqual(data["lines"][0]["qty"], 2)

    def test_stock_deducted_on_sale(self):
        """Completing a sale deducts stock from the product."""
        before = self.product.stock
        self.client.post(reverse("complete-sale"), {
            "items": [{"product_id": str(self.product.id), "qty": 3}],
            "payment_method": "Cash",
            "till_number": "Till #1",
        }, format="json")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, before - 3)

    def test_discount_applied_correctly(self):
        """5% discount reduces subtotal before VAT calculation."""
        resp = self.client.post(reverse("complete-sale"), {
            "items": [{"product_id": str(self.product.id), "qty": 1}],
            "payment_method": "Cash",
            "discount_pct": "5.00",
            "till_number": "Till #1",
        }, format="json")
        data = resp.data["data"]
        # subtotal = 28500, discount = 1425, taxable = 27075
        # tax = 27075 × 0.18 = 4873 (int), total = 27075 + 4873 = 31948
        self.assertEqual(data["discount_amount"], 1425)
        self.assertEqual(data["subtotal"], 28500)

    def test_credit_sale_creates_tab(self):
        """Credit payment creates a CreditTab if customer is provided."""
        from apps.customers.models import Customer
        from apps.credits.models import CreditTab

        customer = Customer.objects.create(
            store=self.store,
            name="Fatuma Ally",
            phone="+255 712 999 888",
        )
        resp = self.client.post(reverse("complete-sale"), {
            "items": [{"product_id": str(self.product.id), "qty": 1}],
            "payment_method": "Credit",
            "customer_id": str(customer.id),
            "till_number": "Till #1",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["data"]["status"], "credit")
        # CreditTab should have been created
        self.assertTrue(CreditTab.objects.filter(customer=customer).exists())

    def test_empty_cart_rejected(self):
        """Completing a sale with empty items returns 400."""
        resp = self.client.post(reverse("complete-sale"), {
            "items": [],
            "payment_method": "Cash",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_product_id_rejected(self):
        """Non-existent product ID returns 400."""
        resp = self.client.post(reverse("complete-sale"), {
            "items": [{"product_id": "00000000-0000-0000-0000-000000000000", "qty": 1}],
            "payment_method": "Cash",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class TransactionListTests(TestCase):
    """Test transaction list/detail views."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.cat, self.user = make_base_fixtures()
        p = make_product(self.store, self.cat)
        # Create a transaction manually
        self.txn = Transaction.objects.create(
            store=self.store,
            txn_number="TXN-2001",
            payment_method="Cash",
            status="paid",
            subtotal=28500,
            total=33630,
            tax_amount=5130,
            cost_total=22000,
            profit=6500,
            cashier=self.user,
            till_number="Till #1",
        )
        TransactionLine.objects.create(
            transaction=self.txn,
            product=p,
            product_name=p.name,
            product_sku=p.sku,
            unit_price=p.price,
            unit_cost=p.cost,
            qty=1,
        )
        resp = self.client.post(reverse("token_obtain_pair"),
                                {"username": "cashier1", "password": "pass123!"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_list_transactions(self):
        """GET /transactions/ returns paginated list."""
        resp = self.client.get(reverse("transaction-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])

    def test_retrieve_transaction(self):
        """GET /transactions/{id}/ returns full detail with lines."""
        resp = self.client.get(reverse("transaction-detail", args=[self.txn.id]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertEqual(data["txn_number"], "TXN-2001")
        self.assertEqual(len(data["lines"]), 1)

    def test_filter_by_status(self):
        """?status=paid filters correctly."""
        resp = self.client.get(reverse("transaction-list") + "?status=paid")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        txn_numbers = [t["txn_number"] for t in resp.data["data"]]
        self.assertIn("TXN-2001", txn_numbers)

    def test_refund_transaction(self):
        """POST /transactions/{id}/refund/ marks as refunded and restores stock."""
        p = make_product(self.store, self.cat, sku="REF-001", stock=10)
        txn = Transaction.objects.create(
            store=self.store, txn_number="TXN-2002",
            payment_method="Cash", status="paid",
            subtotal=p.price, total=p.price,
            cost_total=p.cost, profit=p.price - p.cost,
            cashier=self.user, till_number="Till #1",
        )
        TransactionLine.objects.create(
            transaction=txn, product=p,
            product_name=p.name, product_sku=p.sku,
            unit_price=p.price, unit_cost=p.cost, qty=3,
        )
        before = p.stock  # should be 10

        resp = self.client.post(
            reverse("transaction-refund", args=[txn.id]),
            {"reason": "Customer returned goods"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        txn.refresh_from_db()
        self.assertEqual(txn.status, "refunded")
        # Stock restored
        p.refresh_from_db()
        self.assertEqual(p.stock, before + 3)
