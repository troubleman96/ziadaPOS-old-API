"""
apps/accounts/tests/test_accounts.py

Tests for the accounts app: auth, users, stores, organisations.

Run with:  pytest apps/accounts/tests/
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import AICredit, Organisation, Store, User


# ── Factories (simple inline helpers — no factory_boy needed for accounts) ────

def make_org(name="Test Org"):
    """Create a test organisation."""
    return Organisation.objects.create(name=name, tin="123-456-789")


def make_store(org, name="Test Store", area="Kariakoo"):
    """Create a test store under the given organisation."""
    return Store.objects.create(organisation=org, name=name, area=area, till_count=2)


def make_user(store, username="hamisi", role="admin", password="testpass123"):
    """Create a test user assigned to the given store."""
    return User.objects.create_user(
        username=username,
        password=password,
        first_name="Hamisi",
        last_name="Mwakapaga",
        role=role,
        store=store,
    )


# ── Auth tests ────────────────────────────────────────────────────────────────

class AuthTests(TestCase):
    """Test JWT authentication: login, refresh, verify."""

    def setUp(self):
        """Create fixtures shared by all auth tests."""
        self.client = APIClient()
        self.org = make_org()
        self.store = make_store(self.org)
        self.user = make_user(self.store, password="goodpassword!")

    def test_login_with_valid_credentials(self):
        """POST /api/v1/auth/login/ with correct credentials → 200 + tokens."""
        url = reverse("token_obtain_pair")
        resp = self.client.post(url, {"username": "hamisi", "password": "goodpassword!"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Response must contain both access and refresh tokens
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)

    def test_login_with_wrong_password(self):
        """POST /api/v1/auth/login/ with wrong password → 401."""
        url = reverse("token_obtain_pair")
        resp = self.client.post(url, {"username": "hamisi", "password": "wrongpass"})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_token(self):
        """POST /api/v1/auth/refresh/ with valid refresh → new access token."""
        # First login to get tokens
        login_url = reverse("token_obtain_pair")
        login_resp = self.client.post(login_url, {"username": "hamisi", "password": "goodpassword!"})
        refresh_token = login_resp.data["refresh"]

        # Now refresh
        refresh_url = reverse("token_refresh")
        resp = self.client.post(refresh_url, {"refresh": refresh_token})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)


# ── User / Me tests ───────────────────────────────────────────────────────────

class MeViewTests(TestCase):
    """Test the /me/ endpoint — current user profile."""

    def setUp(self):
        self.client = APIClient()
        self.org = make_org()
        self.store = make_store(self.org)
        self.user = make_user(self.store, password="pass123!")

    def _auth(self):
        """Authenticate the test client with a JWT token."""
        url = reverse("token_obtain_pair")
        resp = self.client.post(url, {"username": "hamisi", "password": "pass123!"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_get_me_unauthenticated(self):
        """GET /api/v1/accounts/me/ without token → 401."""
        resp = self.client.get(reverse("me"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_me_authenticated(self):
        """GET /api/v1/accounts/me/ with valid token → 200 + user data."""
        self._auth()
        resp = self.client.get(reverse("me"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Must include success envelope
        self.assertTrue(resp.data["success"])
        self.assertEqual(resp.data["data"]["username"], "hamisi")
        self.assertEqual(resp.data["data"]["role"], "admin")

    def test_patch_me(self):
        """PATCH /api/v1/accounts/me/ updates phone number."""
        self._auth()
        resp = self.client.patch(reverse("me"), {"phone": "+255 712 999 888"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "+255 712 999 888")


# ── Store tests ───────────────────────────────────────────────────────────────

class StoreTests(TestCase):
    """Test store listing and creation."""

    def setUp(self):
        self.client = APIClient()
        self.org = make_org()
        self.store = make_store(self.org, name="Kariakoo")
        self.admin = make_user(self.store, username="admin_user", role="admin", password="admin123!")
        # Authenticate as admin
        url = reverse("token_obtain_pair")
        resp = self.client.post(url, {"username": "admin_user", "password": "admin123!"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_list_stores(self):
        """GET /api/v1/accounts/stores/ returns stores list."""
        resp = self.client.get(reverse("store-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])

    def test_create_store(self):
        """POST /api/v1/accounts/stores/ creates a new store."""
        resp = self.client.post(reverse("store-list"), {
            "organisation": str(self.org.id),
            "name": "Mwenge Branch",
            "area": "Mwenge",
            "till_count": 1,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Store.objects.filter(name="Mwenge Branch").exists())


# ── AI Credits tests ──────────────────────────────────────────────────────────

class AICreditTests(TestCase):
    """Test AI credit tracking and retrieval."""

    def setUp(self):
        self.client = APIClient()
        self.org = make_org()
        self.store = make_store(self.org)
        self.user = make_user(self.store, password="pass123!")
        url = reverse("token_obtain_pair")
        resp = self.client.post(url, {"username": "hamisi", "password": "pass123!"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_get_ai_credits(self):
        """GET /api/v1/accounts/ai-credits/ → creates and returns current month's credits."""
        resp = self.client.get(reverse("ai-credits"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertIn("used", data)
        self.assertIn("allocated", data)
        self.assertIn("remaining", data)
        # Fresh record should have 0 used
        self.assertEqual(data["used"], 0)

    def test_ai_credit_get_or_create(self):
        """get_or_create_current() is idempotent — multiple calls return same record."""
        c1 = AICredit.get_or_create_current(self.org)
        c2 = AICredit.get_or_create_current(self.org)
        self.assertEqual(c1.id, c2.id)


# ── User model tests ──────────────────────────────────────────────────────────

class UserModelTests(TestCase):
    """Unit tests for User model properties."""

    def setUp(self):
        self.org = make_org()
        self.store = make_store(self.org)
        self.user = make_user(self.store)
        # Set full name
        self.user.first_name = "Hamisi"
        self.user.last_name = "Mwakapaga"
        self.user.save()

    def test_full_name(self):
        self.assertEqual(self.user.full_name, "Hamisi Mwakapaga")

    def test_initials(self):
        self.assertEqual(self.user.initials, "HM")

    def test_role_choices(self):
        """Role must be one of admin / manager / cashier."""
        valid_roles = ["admin", "manager", "cashier"]
        for role in valid_roles:
            self.user.role = role
            self.user.full_clean()  # Should not raise
