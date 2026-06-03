"""
apps/credits/tests/test_credits.py

Tests for the Credits app: CreditTab creation, payment recording,
balance calculation, aging, and communication log.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Organisation, Store, User
from apps.credits.models import CreditMessage, CreditNote, CreditPayment, CreditTab
from apps.customers.models import Customer


def make_base_fixtures():
    """Create org, store, owner, and staff users."""
    org   = Organisation.objects.create(name="Test Org")
    store = Store.objects.create(organisation=org, name="Main Store", area="Kariakoo")
    owner = User.objects.create_user(
        username="0712000001", phone="0712000001", password="pass123!",
        role="owner", store=store,
    )
    staff = User.objects.create_user(
        username="0712000002", phone="0712000002", password="pass123!",
        role="staff", store=store,
    )
    return org, store, owner, staff


def make_customer(store, name="Fatuma Ally", phone="+255 714 100 001"):
    """Create a test customer."""
    return Customer.objects.create(store=store, name=name, phone=phone)


def auth(client, phone, password="pass123!"):
    """Authenticate an APIClient via phone + password."""
    resp = client.post(reverse("login"), {"phone": phone, "password": password})
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['data']['access']}")
    return client


class CreditTabModelTests(TestCase):
    """Unit tests for CreditTab model properties."""

    def setUp(self):
        _, self.store, self.manager, self.cashier = make_base_fixtures()
        self.customer = make_customer(self.store)

    def test_balance_is_amount_minus_paid(self):
        """Tab.balance = amount - amount_paid."""
        tab = CreditTab.objects.create(
            customer=self.customer,
            store=self.store,
            amount=50000,
            amount_paid=20000,
        )
        self.assertEqual(tab.balance, 30000)

    def test_balance_never_negative(self):
        """Tab.balance returns 0 if overpaid (should not happen but is safe)."""
        tab = CreditTab.objects.create(
            customer=self.customer,
            store=self.store,
            amount=50000,
            amount_paid=60000,
        )
        self.assertEqual(tab.balance, 0)

    def test_is_overdue_true_for_past_due_date(self):
        """Tab is overdue if due_date is in the past and not settled."""
        yesterday = date.today() - timedelta(days=1)
        tab = CreditTab.objects.create(
            customer=self.customer,
            store=self.store,
            amount=50000,
            due_date=yesterday,
            status=CreditTab.STATUS_OPEN,
        )
        self.assertTrue(tab.is_overdue)

    def test_is_overdue_false_for_future_due_date(self):
        """Tab is NOT overdue if due_date is in the future."""
        next_week = date.today() + timedelta(days=7)
        tab = CreditTab.objects.create(
            customer=self.customer,
            store=self.store,
            amount=50000,
            due_date=next_week,
            status=CreditTab.STATUS_OPEN,
        )
        self.assertFalse(tab.is_overdue)

    def test_is_overdue_false_for_settled_tab(self):
        """Settled tabs are not considered overdue."""
        yesterday = date.today() - timedelta(days=1)
        tab = CreditTab.objects.create(
            customer=self.customer,
            store=self.store,
            amount=50000,
            amount_paid=50000,
            due_date=yesterday,
            status=CreditTab.STATUS_SETTLED,
        )
        self.assertFalse(tab.is_overdue)


class RecordPaymentTests(TestCase):
    """Test POST /credits/customers/{id}/record-payment/ endpoint."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.manager, self.cashier = make_base_fixtures()
        auth(self.client, "0712000002")

        self.customer = make_customer(self.store)
        # Create an open tab for 50,000 TZS
        self.tab = CreditTab.objects.create(
            customer=self.customer,
            store=self.store,
            amount=50000,
            status=CreditTab.STATUS_OPEN,
        )
        # Sync open_credit cache on customer
        self.customer.open_credit = 50000
        self.customer.save()

    def test_full_payment_settles_tab(self):
        """Paying the full amount marks the tab as settled."""
        resp = self.client.post(
            reverse("credits-record-payment", args=[self.customer.id]),
            {"amount": 50000, "method": "Cash"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        self.tab.refresh_from_db()
        self.assertEqual(self.tab.status, CreditTab.STATUS_SETTLED)
        self.assertEqual(self.tab.amount_paid, 50000)

    def test_partial_payment_marks_partial(self):
        """Paying less than the full amount marks the tab as partially_paid."""
        resp = self.client.post(
            reverse("credits-record-payment", args=[self.customer.id]),
            {"amount": 20000, "method": "M-Pesa", "reference": "QGT5K3AB"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        self.tab.refresh_from_db()
        self.assertEqual(self.tab.status, CreditTab.STATUS_PARTIAL)
        self.assertEqual(self.tab.amount_paid, 20000)

    def test_customer_open_credit_updated(self):
        """After payment, Customer.open_credit is recalculated."""
        self.client.post(
            reverse("credits-record-payment", args=[self.customer.id]),
            {"amount": 30000, "method": "Cash"},
            format="json",
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.open_credit, 20000)

    def test_no_balance_rejected(self):
        """Recording payment when balance is zero returns 400."""
        # Settle the tab first
        self.customer.open_credit = 0
        self.customer.save()
        resp = self.client.post(
            reverse("credits-record-payment", args=[self.customer.id]),
            {"amount": 1000, "method": "Cash"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_payment_distributes_across_multiple_tabs(self):
        """Payment covers first tab fully, then partially covers second tab."""
        # Create a second tab
        tab2 = CreditTab.objects.create(
            customer=self.customer,
            store=self.store,
            amount=30000,
            status=CreditTab.STATUS_OPEN,
        )
        self.customer.open_credit = 80000  # 50k + 30k
        self.customer.save()

        resp = self.client.post(
            reverse("credits-record-payment", args=[self.customer.id]),
            {"amount": 60000, "method": "Cash"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        # First tab (50k) should be settled
        self.tab.refresh_from_db()
        self.assertEqual(self.tab.status, CreditTab.STATUS_SETTLED)

        # Second tab (30k) should have 10k applied
        tab2.refresh_from_db()
        self.assertEqual(tab2.amount_paid, 10000)
        self.assertEqual(tab2.status, CreditTab.STATUS_PARTIAL)


class SendReminderTests(TestCase):
    """Test POST /credits/customers/{id}/send-reminder/ endpoint."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, _, _ = make_base_fixtures()
        auth(self.client, "0712000002")
        self.customer = make_customer(self.store)
        self.customer.open_credit = 20000
        self.customer.save()

    def test_log_whatsapp_reminder(self):
        """Sending a WhatsApp reminder creates a CreditMessage."""
        resp = self.client.post(
            reverse("credits-send-reminder", args=[self.customer.id]),
            {
                "kind": "whatsapp",
                "direction": "out",
                "body": "Habari Fatuma, deni lako TZS 20,000 linahitajika.",
                "who": "Hamisi M.",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(CreditMessage.objects.filter(customer=self.customer).exists())

    def test_log_inbound_customer_reply(self):
        """Inbound direction stores customer's reply."""
        resp = self.client.post(
            reverse("credits-send-reminder", args=[self.customer.id]),
            {
                "kind": "whatsapp",
                "direction": "in",
                "body": "Nitakuja kesho kulipa.",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        msg = CreditMessage.objects.get(customer=self.customer)
        self.assertEqual(msg.direction, "in")


class AddNoteTests(TestCase):
    """Test POST /credits/customers/{id}/add-note/ endpoint."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, _, _ = make_base_fixtures()
        auth(self.client, "0712000002")
        self.customer = make_customer(self.store)

    def test_add_internal_note(self):
        """Adding a note creates a CreditNote."""
        resp = self.client.post(
            reverse("credits-add-note", args=[self.customer.id]),
            {"body": "Customer pays reliably end of month."},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(CreditNote.objects.filter(customer=self.customer).exists())


class WriteOffTests(TestCase):
    """Test POST /credits/tabs/{id}/write-off/ endpoint."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, self.manager, self.cashier = make_base_fixtures()
        auth(self.client, "0712000001")  # Owner only

        self.customer = make_customer(self.store)
        self.tab = CreditTab.objects.create(
            customer=self.customer,
            store=self.store,
            amount=25000,
            status=CreditTab.STATUS_OPEN,
        )
        self.customer.open_credit = 25000
        self.customer.save()

    def test_write_off_tab(self):
        """Manager can write off an open tab."""
        resp = self.client.post(
            reverse("credits-write-off", args=[self.tab.id]),
            {"reason": "Customer untraceable after relocation"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.tab.refresh_from_db()
        self.assertEqual(self.tab.status, CreditTab.STATUS_WRITTEN_OFF)
        self.assertEqual(self.tab.write_off_reason, "Customer untraceable after relocation")

    def test_write_off_updates_customer_credit(self):
        """Writing off tab reduces Customer.open_credit to 0."""
        self.client.post(
            reverse("credits-write-off", args=[self.tab.id]),
            {"reason": "Bad debt"},
            format="json",
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.open_credit, 0)

    def test_cashier_cannot_write_off(self):
        """Cashier does not have permission to write off tabs."""
        auth(self.client, "0712000002")
        resp = self.client.post(
            reverse("credits-write-off", args=[self.tab.id]),
            {"reason": "Not allowed"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_settled_tab_cannot_be_written_off(self):
        """Cannot write off an already settled tab."""
        self.tab.status = CreditTab.STATUS_SETTLED
        self.tab.save()
        resp = self.client.post(
            reverse("credits-write-off", args=[self.tab.id]),
            {"reason": "Test"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class CreditsDashboardTests(TestCase):
    """Test GET /credits/ dashboard endpoint."""

    def setUp(self):
        self.client = APIClient()
        _, self.store, _, _ = make_base_fixtures()
        auth(self.client, "0712000002")

        self.customer = make_customer(self.store, name="Juma Kifupi", phone="+255 712 990 102")
        self.customer.open_credit = 84200
        self.customer.save()

        CreditTab.objects.create(
            customer=self.customer,
            store=self.store,
            amount=84200,
            due_date=date.today() + timedelta(days=6),
            status=CreditTab.STATUS_OPEN,
        )

    def test_dashboard_returns_kpis(self):
        """Dashboard returns KPI data."""
        resp = self.client.get(reverse("credits-dashboard"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertIn("kpis", data)
        self.assertIn("aging_buckets", data)
        self.assertIn("customers", data)

    def test_kpi_total_outstanding_correct(self):
        """KPI total_outstanding = sum of open_credit for customers with balance."""
        resp = self.client.get(reverse("credits-dashboard"))
        data = resp.data["data"]
        self.assertEqual(data["kpis"]["total_outstanding"], 84200)

    def test_aging_buckets_sum_is_correct(self):
        """Aging buckets total equals total outstanding."""
        resp = self.client.get(reverse("credits-dashboard"))
        data = resp.data["data"]
        total = sum(b["amount"] for b in data["aging_buckets"])
        self.assertEqual(total, 84200)
