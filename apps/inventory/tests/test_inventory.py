"""
apps/inventory/tests/test_inventory.py

Tests for inventory: products, categories, suppliers, stock adjustments.

Run with:  pytest apps/inventory/tests/
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Organisation, Store, User
from apps.inventory.models import Category, Product, StockAdjustment
from apps.suppliers.models import Supplier


# ── Shared fixtures ───────────────────────────────────────────────────────────

def make_fixtures():
    """Create the shared test fixtures needed by most tests."""
    org   = Organisation.objects.create(name="Test Org")
    store = Store.objects.create(organisation=org, name="Main Store", area="Kariakoo")
    cat   = Category.objects.create(name="Grocery", sort_order=1)
    sup   = Supplier.objects.create(name="Test Supplier", store=store, organisation=org)
    user  = User.objects.create_user(
        username="manager",
        password="pass123!",
        role="manager",
        store=store,
    )
    return org, store, cat, sup, user


def make_product(store, category, supplier, **kwargs):
    """Create a test product with sensible defaults."""
    defaults = {
        "name": "Unga wa Sembe 10kg",
        "sku": "UWS-001",
        "price": 28500,
        "cost": 22000,
        "stock": 42,
        "min_stock": 10,
        "max_stock": 80,
        "unit": "bag",
        "weekly_sold": 50,
        "category": category,
        "supplier": supplier,
    }
    defaults.update(kwargs)
    return Product.objects.create(store=store, **defaults)


# ── Category tests ────────────────────────────────────────────────────────────

class CategoryTests(TestCase):
    """Test category listing."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, _, _, self.user = make_fixtures()
        # Authenticate
        resp = self.client.post(reverse("token_obtain_pair"),
                                {"username": "manager", "password": "pass123!"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_list_categories(self):
        """GET /api/v1/inventory/categories/ returns all categories."""
        resp = self.client.get(reverse("category-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])
        # At least the "Grocery" category we created
        names = [c["name"] for c in resp.data["data"]]
        self.assertIn("Grocery", names)


# ── Product tests ─────────────────────────────────────────────────────────────

class ProductTests(TestCase):
    """Test product CRUD and extra actions."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.cat, self.sup, self.user = make_fixtures()
        self.product = make_product(self.store, self.cat, self.sup)
        # Authenticate
        resp = self.client.post(reverse("token_obtain_pair"),
                                {"username": "manager", "password": "pass123!"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_list_products(self):
        """GET /api/v1/inventory/products/ returns paginated list."""
        resp = self.client.get(reverse("product-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])
        self.assertIn("meta", resp.data)  # paginated

    def test_retrieve_product(self):
        """GET /api/v1/inventory/products/{id}/ returns product with computed fields."""
        resp = self.client.get(reverse("product-detail", args=[self.product.id]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertEqual(data["name"], "Unga wa Sembe 10kg")
        # Computed fields must be present
        self.assertIn("margin_pct", data)
        self.assertIn("stock_status", data)
        self.assertIn("days_of_stock", data)

    def test_create_product(self):
        """POST /api/v1/inventory/products/ creates a product."""
        resp = self.client.post(reverse("product-list"), {
            "name": "Sukari 2kg",
            "sku": "SUG-002",
            "price": 7000,
            "cost": 5400,
            "stock": 60,
            "min_stock": 20,
            "max_stock": 100,
            "unit": "pack",
            "category": str(self.cat.id),
            "supplier": str(self.sup.id),
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Product.objects.filter(sku="SUG-002").exists())

    def test_create_product_opening_stock_signal(self):
        """Creating a product with stock > 0 creates an opening adjustment."""
        Product.objects.create(
            store=self.store,
            name="New Product",
            sku="NEW-001",
            price=5000,
            cost=3000,
            stock=25,
            min_stock=5,
            max_stock=50,
        )
        adj = StockAdjustment.objects.filter(
            product__sku="NEW-001",
            adjustment_type=StockAdjustment.TYPE_OPENING,
        )
        self.assertTrue(adj.exists())
        self.assertEqual(adj.first().quantity_after, 25)

    def test_filter_low_stock(self):
        """GET /api/v1/inventory/products/low-stock/ returns only low-stock products."""
        # Make one low-stock product
        low = make_product(
            self.store, self.cat, self.sup,
            name="Low Stock Item", sku="LOW-001",
            stock=3, min_stock=15,
        )
        resp = self.client.get(reverse("product-low-stock"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        skus = [p["sku"] for p in resp.data["data"]]
        self.assertIn("LOW-001", skus)

    def test_adjust_stock(self):
        """POST /products/{id}/adjust-stock/ changes stock and creates audit record."""
        before = self.product.stock
        resp = self.client.post(
            reverse("product-adjust-stock", args=[self.product.id]),
            {"quantity_change": -5, "note": "Damaged in transit"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, before - 5)

        # Audit record must exist
        adj = StockAdjustment.objects.filter(
            product=self.product,
            adjustment_type=StockAdjustment.TYPE_MANUAL,
        )
        self.assertTrue(adj.exists())
        self.assertEqual(adj.first().quantity_change, -5)

    def test_margin_calculation(self):
        """Product.margin_pct is calculated correctly."""
        # margin = (28500 - 22000) / 28500 * 100 ≈ 22.8%
        self.assertAlmostEqual(self.product.margin_pct, 22.8, delta=0.1)

    def test_stock_status_active(self):
        """stock > min → status is 'active'."""
        self.assertEqual(self.product.stock_status, "active")  # 42 > 10

    def test_stock_status_low(self):
        """stock <= min → status is 'low'."""
        self.product.stock = 10  # equals min_stock
        self.product.save()
        self.assertEqual(self.product.stock_status, "low")

    def test_stock_status_out(self):
        """stock == 0 → status is 'out'."""
        self.product.stock = 0
        self.product.save()
        self.assertEqual(self.product.stock_status, "out")

    def test_soft_delete(self):
        """DELETE /products/{id}/ marks as inactive, doesn't destroy record."""
        resp = self.client.delete(reverse("product-detail", args=[self.product.id]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)
        # Record still exists in DB
        self.assertTrue(Product.objects.filter(id=self.product.id).exists())
