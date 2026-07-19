from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Organisation, Store, User
from apps.expenses.models import Expense


def make_base_fixtures():
    org = Organisation.objects.create(name="Test Org")
    store = Store.objects.create(organisation=org, name="Main", area="Kariakoo")
    owner = User.objects.create_user(
        username="0712000001", phone="0712000001", password="pass123!",
        role="owner", store=store,
    )
    staff = User.objects.create_user(
        username="0712000002", phone="0712000002", password="pass123!",
        role="staff", store=store,
    )
    return org, store, owner, staff


def auth(client, phone="0712000002", password="pass123!"):
    resp = client.post(reverse("login"), {"phone": phone, "password": password})
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")


class ExpenseTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        _, self.store, _, self.staff = make_base_fixtures()
        auth(self.client)

    def test_create_expense(self):
        resp = self.client.post(
            reverse("expense-list"),
            {"title": "Office supplies", "category": "Supplies",
             "amount": 25000, "payment_method": "Cash"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(Expense.objects.first().amount, 25000)

    def test_list_expenses_store_scoped(self):
        Expense.objects.create(store=self.store, title="A", amount=100,
                               category="Other", recorded_by=self.staff)
        Expense.objects.create(store=self.store, title="B", amount=200,
                               category="Rent", recorded_by=self.staff)
        resp = self.client.get(reverse("expense-list"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["data"]), 2)

    def test_summary(self):
        Expense.objects.create(store=self.store, title="A", amount=1000,
                               category="Rent", recorded_by=self.staff)
        Expense.objects.create(store=self.store, title="B", amount=2000,
                               category="Rent", recorded_by=self.staff)
        Expense.objects.create(store=self.store, title="C", amount=500,
                               category="Supplies", recorded_by=self.staff)
        resp = self.client.get(reverse("expense-summary"))
        self.assertEqual(resp.status_code, 200)
        d = resp.data["data"]
        self.assertEqual(d["total_amount"], 3500)
        self.assertEqual(d["total_count"], 3)

    def test_delete_expense(self):
        e = Expense.objects.create(store=self.store, title="Test", amount=100,
                                   category="Other", recorded_by=self.staff)
        resp = self.client.delete(reverse("expense-detail", args=[e.id]))
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(Expense.objects.count(), 0)
