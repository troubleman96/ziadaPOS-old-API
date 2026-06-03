"""
apps/accounts/tests/test_accounts.py

Tests for the accounts app: auth, users, stores, organisations.
Updated for phone-based login and new roles (owner/staff).
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import AICredit, Organisation, Store, User


# ── Factories ─────────────────────────────────────────────────────────────────

def make_org(name="Test Org"):
    return Organisation.objects.create(name=name, tin="123-456-789")


def make_store(org, name="Test Store", area="Kariakoo"):
    return Store.objects.create(organisation=org, name=name, area=area, till_count=2)


def make_user(store, phone="0712000001", role="owner", password="testpass123", organisation=None):
    """Create a test user. Phone is the login field (10 digits)."""
    return User.objects.create_user(
        username=phone,           # username auto-synced to phone by model.save()
        phone=phone,
        password=password,
        first_name="Hamisi",
        last_name="Mwakapaga",
        role=role,
        store=store,
        organisation=organisation,
    )


def _login(client, phone, password="testpass123"):
    """Return a JWT-authenticated APIClient."""
    resp = client.post(reverse("login"), {"phone": phone, "password": password})
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['data']['access']}")
    return resp


# ── Auth tests ────────────────────────────────────────────────────────────────

class AuthTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.org   = make_org()
        self.store = make_store(self.org)
        self.user  = make_user(self.store, phone="0712000001", password="goodpassword!")

    def test_login_with_valid_credentials(self):
        """POST /api/v1/auth/login/ with correct phone+password → 200 + tokens."""
        resp = self.client.post(reverse("login"), {
            "phone": "0712000001", "password": "goodpassword!"
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access",  resp.data["data"])
        self.assertIn("refresh", resp.data["data"])

    def test_login_with_wrong_password(self):
        """POST /api/v1/auth/login/ with wrong password → 401."""
        resp = self.client.post(reverse("login"), {
            "phone": "0712000001", "password": "wrongpass"
        })
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_unknown_phone(self):
        """POST /api/v1/auth/login/ with unknown phone → 401."""
        resp = self.client.post(reverse("login"), {
            "phone": "0799999999", "password": "goodpassword!"
        })
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_token(self):
        """POST /api/v1/auth/refresh/ with valid refresh → new access token."""
        login_resp = self.client.post(reverse("login"), {
            "phone": "0712000001", "password": "goodpassword!"
        })
        refresh_token = login_resp.data["data"]["refresh"]

        resp = self.client.post(reverse("token_refresh"), {"refresh": refresh_token})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)


# ── User / Me tests ───────────────────────────────────────────────────────────

class MeViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.org   = make_org()
        self.store = make_store(self.org)
        self.user  = make_user(self.store, phone="0712000001", password="pass123!")

    def _auth(self):
        _login(self.client, "0712000001", "pass123!")

    def test_get_me_unauthenticated(self):
        """GET /api/v1/accounts/me/ without token → 401."""
        resp = self.client.get(reverse("me"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_me_authenticated(self):
        """GET /api/v1/accounts/me/ with valid token → 200 + user data."""
        self._auth()
        resp = self.client.get(reverse("me"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])
        # Phone is the login identifier
        self.assertEqual(resp.data["data"]["user"]["phone"], "0712000001")
        self.assertEqual(resp.data["data"]["user"]["role"], "owner")

    def test_patch_me_updates_first_name(self):
        """PATCH /api/v1/accounts/me/ can update first name."""
        self._auth()
        resp = self.client.patch(reverse("me"), {"first_name": "Juma"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Juma")


# ── Store tests ───────────────────────────────────────────────────────────────

class StoreTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.org   = make_org()
        self.store = make_store(self.org, name="Kariakoo")
        # Use admin role so StoreViewSet.create can find the organisation
        self.owner = make_user(
            self.store, phone="0712000005", role="owner", password="admin123!",
            organisation=self.org,
        )
        _login(self.client, "0712000005", "admin123!")

    def test_list_stores(self):
        """GET /api/v1/accounts/stores/ returns stores list."""
        resp = self.client.get(reverse("store-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])

    def test_create_store(self):
        """POST /api/v1/accounts/stores/ creates a new store (within max_stores=3)."""
        resp = self.client.post(reverse("store-list"), {
            "organisation": str(self.org.id),
            "name":         "Mwenge Branch",
            "area":         "Mwenge",
            "till_count":   1,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Store.objects.filter(name="Mwenge Branch").exists())


# ── AI Credits tests ──────────────────────────────────────────────────────────

class AICreditTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.org   = make_org()
        self.store = make_store(self.org)
        self.user  = make_user(self.store, phone="0712000001", password="pass123!",
                               organisation=self.org)
        _login(self.client, "0712000001", "pass123!")

    def test_get_ai_credits(self):
        """GET /api/v1/accounts/ai-credits/ → creates and returns current month's credits."""
        resp = self.client.get(reverse("ai-credits"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertIn("used",      data)
        self.assertIn("allocated", data)
        self.assertIn("remaining", data)
        self.assertEqual(data["used"], 0)

    def test_ai_credit_get_or_create(self):
        """get_or_create_current() is idempotent."""
        c1 = AICredit.get_or_create_current(self.org)
        c2 = AICredit.get_or_create_current(self.org)
        self.assertEqual(c1.id, c2.id)


# ── User model tests ──────────────────────────────────────────────────────────

class UserModelTests(TestCase):

    def setUp(self):
        self.org   = make_org()
        self.store = make_store(self.org)
        self.user  = make_user(self.store)
        self.user.first_name = "Hamisi"
        self.user.last_name  = "Mwakapaga"
        self.user.save()

    def test_full_name(self):
        self.assertEqual(self.user.full_name, "Hamisi Mwakapaga")

    def test_initials(self):
        self.assertEqual(self.user.initials, "HM")

    def test_role_choices(self):
        """Role must be one of admin / owner / staff."""
        for role in ["admin", "owner", "staff"]:
            self.user.role = role
            self.user.full_clean()  # Should not raise

    def test_phone_is_username(self):
        """Username is automatically synced to phone number."""
        self.assertEqual(self.user.username, self.user.phone)

    def test_get_organisation_via_store(self):
        """get_organisation returns org via store FK when no direct org FK."""
        self.user.organisation = None
        self.user.save()
        self.assertEqual(self.user.get_organisation, self.store.organisation)
