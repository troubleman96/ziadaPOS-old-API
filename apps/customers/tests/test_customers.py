"""
apps/customers/tests/test_customers.py

Tests for the Customer API: list, create, update, soft-delete, summary.
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Organisation, Store, User
from apps.customers.models import Customer


def make_base_fixtures():
    """Create shared org, store, manager, and cashier users."""
    org     = Organisation.objects.create(name="Test Org")
    store   = Store.objects.create(organisation=org, name="Main", area="Kariakoo")
    manager = User.objects.create_user(
        username="mgr1", password="pass123!", role="manager", store=store
    )
    cashier = User.objects.create_user(
        username="cashier1", password="pass123!", role="cashier", store=store
    )
    return org, store, manager, cashier


def auth(client, username, password="pass123!"):
    """Authenticate APIClient and return it."""
    resp = client.post(reverse("token_obtain_pair"), {"username": username, "password": password})
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return client


class CustomerListTests(TestCase):
    """Test GET /customers/ list endpoint."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.manager, _ = make_base_fixtures()
        auth(self.client, "mgr1")

        # Create a few customers
        Customer.objects.create(store=self.store, name="Fatuma Ally",   phone="+255 714 100 001", segment="VIP",      total_spent=1200000)
        Customer.objects.create(store=self.store, name="Juma Kifupi",   phone="+255 714 100 002", segment="Regular",  total_spent=400000)
        Customer.objects.create(store=self.store, name="Hassan Bakari", phone="+255 714 100 003", segment="New",      total_spent=80000)

    def test_list_returns_all_active(self):
        """GET /customers/ returns all active customers."""
        resp = self.client.get(reverse("customer-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])

    def test_filter_by_segment(self):
        """?segment=VIP returns only VIP customers."""
        resp = self.client.get(reverse("customer-list") + "?segment=VIP")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # All returned customers should be VIP
        # (pagination wraps in data key)
        for customer in resp.data.get("data", resp.data.get("results", [])):
            self.assertEqual(customer["segment"], "VIP")

    def test_search_by_name(self):
        """?search=Fatuma returns matching customers."""
        resp = self.client.get(reverse("customer-list") + "?search=Fatuma")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unauthenticated_denied(self):
        """Unauthenticated request is rejected."""
        client = APIClient()
        resp = client.get(reverse("customer-list"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class CustomerCreateTests(TestCase):
    """Test POST /customers/ create endpoint."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.manager, self.cashier = make_base_fixtures()

    def test_manager_can_create(self):
        """Manager can add a new customer."""
        auth(self.client, "mgr1")
        resp = self.client.post(reverse("customer-list"), {
            "name": "Zawadi Chaka",
            "phone": "+255 769 789 012",
            "segment": "New",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["data"]["name"], "Zawadi Chaka")

    def test_cashier_cannot_create(self):
        """Cashier does not have permission to create customers."""
        auth(self.client, "cashier1")
        resp = self.client.post(reverse("customer-list"), {
            "name": "Unauthorised User",
            "phone": "+255 769 000 001",
            "segment": "New",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_phone_rejected(self):
        """Duplicate phone within the same store is rejected."""
        auth(self.client, "mgr1")
        Customer.objects.create(
            store=self.store, name="Fatuma Ally", phone="+255 714 100 001"
        )
        resp = self.client.post(reverse("customer-list"), {
            "name": "Other Person",
            "phone": "+255 714 100 001",
            "segment": "New",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_name_rejected(self):
        """Name is required."""
        auth(self.client, "mgr1")
        resp = self.client.post(reverse("customer-list"), {
            "phone": "+255 769 000 002",
            "segment": "New",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class CustomerDetailTests(TestCase):
    """Test GET/PATCH/DELETE for a single customer."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.manager, self.cashier = make_base_fixtures()
        auth(self.client, "mgr1")
        self.customer = Customer.objects.create(
            store=self.store, name="Asha Mwinyi", phone="+255 718 003 982",
            segment="Regular", total_spent=430000,
        )

    def test_retrieve_customer(self):
        """GET /customers/{id}/ returns full profile."""
        resp = self.client.get(reverse("customer-detail", args=[self.customer.id]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["name"], "Asha Mwinyi")

    def test_partial_update_segment(self):
        """PATCH can change the customer segment."""
        resp = self.client.patch(
            reverse("customer-detail", args=[self.customer.id]),
            {"segment": "VIP"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.segment, "VIP")

    def test_soft_delete(self):
        """DELETE sets is_active=False and returns 204."""
        resp = self.client.delete(reverse("customer-detail", args=[self.customer.id]))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)

    def test_soft_deleted_hidden_from_list(self):
        """Soft-deleted customer does not appear in the default list."""
        self.customer.is_active = False
        self.customer.save()
        resp = self.client.get(reverse("customer-list"))
        names = [c["name"] for c in resp.data.get("data", resp.data.get("results", []))]
        self.assertNotIn("Asha Mwinyi", names)


class CustomerModelTests(TestCase):
    """Unit tests for Customer model properties."""

    def setUp(self):
        org   = Organisation.objects.create(name="Org")
        store = Store.objects.create(organisation=org, name="Store", area="Area")
        self.customer = Customer.objects.create(
            store=store, name="Fatuma Ally", phone="+255 714 000 001"
        )

    def test_initials_two_word_name(self):
        """'Fatuma Ally' → 'FA'"""
        self.assertEqual(self.customer.initials, "FA")

    def test_has_open_credit_false_by_default(self):
        """New customer has no open credit."""
        self.assertFalse(self.customer.has_open_credit)

    def test_has_open_credit_true_when_positive(self):
        """Customer with open_credit > 0 has_open_credit = True."""
        self.customer.open_credit = 50000
        self.customer.save()
        self.assertTrue(self.customer.has_open_credit)

    def test_str_representation(self):
        """__str__ includes name and store."""
        self.assertIn("Fatuma Ally", str(self.customer))


class CustomerSummaryTests(TestCase):
    """Test GET /customers/summary/ KPI endpoint."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.manager, _ = make_base_fixtures()
        auth(self.client, "mgr1")

        Customer.objects.create(store=self.store, name="Cust 1", phone="+255 700 000 001", segment="VIP",      total_spent=1000000, open_credit=50000)
        Customer.objects.create(store=self.store, name="Cust 2", phone="+255 700 000 002", segment="Regular",  total_spent=300000,  open_credit=0)
        Customer.objects.create(store=self.store, name="Cust 3", phone="+255 700 000 003", segment="New",      total_spent=50000,   open_credit=0)

    def test_summary_returns_counts(self):
        """Summary endpoint returns correct total_customers."""
        resp = self.client.get(reverse("customer-summary"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertEqual(data["total_customers"], 3)
        self.assertEqual(data["on_credit_count"], 1)
