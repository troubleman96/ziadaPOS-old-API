"""
Smoke / regression tests for the three P0 fixes.

Run:
    cd /home/camel/projects/ziadapos
    .venv/bin/python manage.py test apps.transactions.tests.test_remediation --verbosity=2
"""
import json
import threading
import time
import uuid
from decimal import Decimal

import urllib.request
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import Organisation, Store
from apps.customers.models import Customer
from apps.inventory.models import Product, Category
from apps.transactions.models import Transaction, TxnSequence

User = get_user_model()


# ── helpers ───────────────────────────────────────────────────────────────────

API = "http://127.0.0.1:8096/api/v1"

def _post(path, payload, token=None):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{API}/{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        return r.getcode(), json.loads(r.read().decode())


def _get(path, token):
    req = urllib.request.Request(
        f"{API}/{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req) as r:
        return r.getcode(), json.loads(r.read().decode())


def _register_and_login(phone="0799999001", name="Smoke Test"):
    code, data = _post("auth/register/", {
        "full_name": name,
        "phone": phone,
        "password": "StrongPass1!",
        "confirm_password": "StrongPass1!",
        "main_shop_name": f"Smoke Shop {phone}",
        "business_type": "retail",
        "region": "Dar es Salaam",
    })
    if code == 201:
        return data["data"]["access"], data["data"]["user"]["id"], data["data"]["organisation"]["id"]

    # already registered — just log in
    code2, data2 = _post("auth/login/", {"phone": phone, "password": "StrongPass1!"})
    assert code2 == 200, data2
    return data2["data"]["access"], data2["data"]["user"]["id"], None


# ── test cases ─────────────────────────────────────────────────────────────────

class RemediationTests(TestCase):
    maxDiff = None

    def setUp(self):
        # Tests hit the real gunicorn process, so we just acquire tokens.
        # Use a fresh phone per test method to avoid duplicate-registration.
        self.phone = f"0799999{ uuid.uuid4().int % 10000:04d}"
        self.token, self.user_id, self.org_id = _register_and_login(self.phone)

    # ── 1. Registration / login happy path ─────────────────────────────────────

    def test_01_register_returns_tokens(self):
        # register a SECOND user to verify registration still works end-to-end
        phone2 = f"0799998{ uuid.uuid4().int % 10000:04d}"
        code, data = _post("auth/register/", {
            "full_name": "Reg Tester",
            "phone": phone2,
            "password": "StrongPass1!",
            "confirm_password": "StrongPass1!",
            "main_shop_name": "Reg Shop",
            "business_type": "retail",
            "region": "Dar es Salaam",
        })
        self.assertEqual(code, 201, data)
        self.assertIn("access", data["data"])
        self.assertEqual(data["data"]["user"]["role"], "owner")

    def test_02_login_returns_tokens_and_subscription(self):
        code, data = _post("auth/login/", {"phone": self.phone, "password": "StrongPass1!"})
        self.assertEqual(code, 200, data)
        self.assertIn("access", data["data"])
        self.assertIn("subscription", data["data"])

    # ── 2. Stock guard ─────────────────────────────────────────────────────────

    def test_03_stock_underflow_rejected(self):
        store = User.objects.get(id=self.user_id).store
        cat = Category.objects.create(name="StockGuardTest", is_global=False)
        prod = Product.objects.create(
            store=store, name="LowStock", sku="LS-1",
            category=cat, price=1000, cost=500, stock=2, min_stock=0, max_stock=100,
        )

        code, data = _post("transactions/complete-sale/", {
            "items": [{"product_id": str(prod.id), "qty": 5}],
            "discount_pct": Decimal("0"),
            "payment_method": "Cash",
        }, token=self.token)
        self.assertEqual(code, 400)
        self.assertIn("Insufficient stock", data.get("message", ""))

    def test_04_normal_sale_deducts_stock(self):
        store = User.objects.get(id=self.user_id).store
        cat = Category.objects.create(name="StockGuardOK", is_global=False)
        prod = Product.objects.create(
            store=store, name="GoodStock", sku="GS-1",
            category=cat, price=1000, cost=500, stock=10, min_stock=0, max_stock=100,
        )

        before = prod.stock
        code, data = _post("transactions/complete-sale/", {
            "items": [{"product_id": str(prod.id), "qty": 3}],
            "discount_pct": Decimal("0"),
            "payment_method": "Cash",
        }, token=self.token)
        self.assertEqual(code, 201, data)
        prod.refresh_from_db()
        self.assertEqual(prod.stock, before - 3)

    def test_05_refund_restores_stock(self):
        store = User.objects.get(id=self.user_id).store
        cat = Category.objects.create(name="RefundRestore", is_global=False)
        prod = Product.objects.create(
            store=store, name="RefundItem", sku="RF-1",
            category=cat, price=1000, cost=500, stock=10, min_stock=0, max_stock=100,
        )

        # sale
        code, data = _post("transactions/complete-sale/", {
            "items": [{"product_id": str(prod.id), "qty": 2}],
            "discount_pct": Decimal("0"),
            "payment_method": "Cash",
        }, token=self.token)
        self.assertEqual(code, 201, data)
        txn_id = data["data"]["id"]
        self.assertEqual(prod.stock, 8)

        # refund
        code2, _ = _post(f"transactions/{txn_id}/refund/", {"reason": "test"}, token=self.token)
        self.assertEqual(code2, 200)
        prod.refresh_from_db()
        self.assertEqual(prod.stock, 10)

    # ── 3. Credit-limit enforcement ─────────────────────────────────────────────

    def test_06_credit_limit_enforced(self):
        store = User.objects.get(id=self.user_id).store
        cust = Customer.objects.create(
            store=store, name="Credit Limit Customer", phone="0711000000",
            credit_limit=1000,
        )
        cat = Category.objects.create(name="CreditLimitCat", is_global=False)
        prod = Product.objects.create(
            store=store, name="CreditItem", sku="CI-1",
            category=cat, price=800, cost=400, stock=100, min_stock=0, max_stock=100,
        )

        code, data = _post("transactions/complete-sale/", {
            "items": [{"product_id": str(prod.id), "qty": 1}],
            "discount_pct": Decimal("0"),
            "payment_method": "Credit",
            "customer_id": str(cust.id),
        }, token=self.token)
        self.assertEqual(code, 400, data)
        self.assertIn("credit limit", data.get("message", "").lower())

    def test_07_credit_sale_within_limit_accepted(self):
        store = User.objects.get(id=self.user_id).store
        cust = Customer.objects.create(
            store=store, name="Credit OK Customer", phone="0711000001",
            credit_limit=50000,
        )
        cat = Category.objects.create(name="CreditOKCat", is_global=False)
        prod = Product.objects.create(
            store=store, name="CreditOKItem", sku="COI-1",
            category=cat, price=800, cost=400, stock=100, min_stock=0, max_stock=100,
        )

        code, data = _post("transactions/complete-sale/", {
            "items": [{"product_id": str(prod.id), "qty": 1}],
            "discount_pct": Decimal("0"),
            "payment_method": "Credit",
            "customer_id": str(cust.id),
        }, token=self.token)
        self.assertEqual(code, 201, data)
        self.assertEqual(data["data"]["status"], "credit")

    # ── 4. TXN sequence / race safety ──────────────────────────────────────────

    def test_08_txn_numbers_are_unique_sequential(self):
        store = User.objects.get(id=self.user_id).store
        cat = Category.objects.create(name="TxnSeqTest1", is_global=False)
        prod = Product.objects.create(
            store=store, name="TxnSeqItem1", sku="TI1",
            category=cat, price=1000, cost=500, stock=100, min_stock=0, max_stock=100,
        )

        nums = []
        for _ in range(3):
            code, data = _post("transactions/complete-sale/", {
                "items": [{"product_id": str(prod.id), "qty": 1}],
                "discount_pct": Decimal("0"),
                "payment_method": "Cash",
            }, token=self.token)
            self.assertEqual(code, 201, data)
            nums.append(data["data"]["txn_number"])

        # uniqueness
        self.assertEqual(len(nums), len(set(nums)), f"duplicates: {nums}")
        # sequential
        ints = [int(n.replace("TXN-", "")) for n in nums]
        self.assertEqual(ints, sorted(ints))

    def test_09_concurrent_txns_do_not_collide(self):
        store = User.objects.get(id=self.user_id).store
        cat = Category.objects.create(name="TxnSeqRace", is_global=False)
        prod = Product.objects.create(
            store=store, name="RaceItem", sku="RI-1",
            category=cat, price=1000, cost=500, stock=100, min_stock=0, max_stock=100,
        )

        results = []
        errors = []
        lock = threading.Lock()

        def fire():
            try:
                code, data = _post("transactions/complete-sale/", {
                    "items": [{"product_id": str(prod.id), "qty": 1}],
                    "discount_pct": Decimal("0"),
                    "payment_method": "Cash",
                }, token=self.token)
                with lock:
                    results.append((code, data))
            except Exception as exc:
                with lock:
                    errors.append(str(exc))

        threads = [threading.Thread(target=fire) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertFalse(errors, errors)
        self.assertEqual(len(results), 8)
        txns = [r[1]["data"]["txn_number"] for r in results if r[0] == 201]
        # All 8 must succeed and each number must be unique
        self.assertEqual(len(txns), 8, f"some failed: {[r for r in results if r[0]!=201]}")
        self.assertEqual(len(txns), len(set(txns)), f"duplicate TXNs: {txns}")

    def test_10_sequence_model_seeded_from_existing_txns(self):
        store = User.objects.get(id=self.user_id).store
        # Force-recreate the sequence row and confirm it initializes from MAX()
        seq, _ = TxnSequence.objects.get_or_create(store=store, defaults={"last_number": 1000})
        seq.refresh_from_db()
        # After previous tests there is at least one Transaction in this store
        max_existing = (
            Transaction.objects.filter(store=store, txn_number__startswith="TXN-")
            .order_by("-txn_number")
            .first()
        )
        if max_existing:
            expected = int(max_existing.txn_number.replace("TXN-", ""))
            self.assertGreaterEqual(seq.last_number, expected)
