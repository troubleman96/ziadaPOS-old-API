"""
apps/subscriptions/tests/test_subscriptions.py

Tests for the subscription system:
  - SubscriptionPlan public listing
  - StoreLimitView (can-add-store gate)
  - Store creation enforces max_stores
  - Admin activates subscription → org.max_stores syncs
  - Admin grants extra stores → org.max_stores syncs
  - StoreViewSet.create returns rich error when at limit
"""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Organisation, Store, User
from apps.subscriptions.models import Subscription, SubscriptionPlan


# ── Test helpers ──────────────────────────────────────────────────────────────

def make_plan(name="Monthly", slug="monthly", price=25000, months=1,
              included_stores=3, extra_price=12000, sort_order=1):
    return SubscriptionPlan.objects.create(
        name=name, slug=slug, price_per_month=price,
        duration_months=months, included_stores=included_stores,
        extra_store_price_per_month=extra_price, is_active=True,
        sort_order=sort_order,
    )


def make_org_with_owner(phone="0712000001", password="pass123!",
                        max_stores=3, plan_slug=None):
    """
    Create Organisation + main Store + owner User.
    Optionally link a SubscriptionPlan.
    """
    org   = Organisation.objects.create(name="Test Org", max_stores=max_stores)
    store = Store.objects.create(
        organisation=org, name="Main Store", area="Kariakoo", is_main_store=True
    )
    owner = User.objects.create_user(
        username=phone, phone=phone, password=password,
        role="owner", store=store, organisation=org,
    )
    # Create trial subscription
    today = date.today()
    sub = Subscription.objects.create(
        organisation=org,
        status=Subscription.STATUS_TRIAL,
        start_date=today,
        end_date=today + timedelta(days=7),
        is_trial=True, trial_fee=10000,
    )
    return org, store, owner, sub


def make_admin(phone="0799000001", password="admin123!"):
    return User.objects.create_user(
        username=phone, phone=phone, password=password, role="admin",
    )


def login(client, phone, password="pass123!"):
    resp = client.post(reverse("login"), {"phone": phone, "password": password})
    assert resp.status_code == 200, f"Login failed for {phone}: {resp.data}"
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['data']['access']}")


# ── SubscriptionPlan public listing ──────────────────────────────────────────

class SubscriptionPlanListTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        make_plan("Monthly",  "monthly",     25000,  1, sort_order=1)
        make_plan("6-Month",  "half-yearly", 23000,  6, sort_order=2)
        make_plan("Yearly",   "yearly",      22000, 12, sort_order=3)

    def test_plans_listed_for_anonymous_user(self):
        """GET /subscriptions/plans/ works without auth."""
        resp = self.client.get(reverse("subscription-plan-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])
        self.assertEqual(len(resp.data["data"]), 3)

    def test_plans_sorted_by_sort_order(self):
        """Plans are returned in sort_order ascending."""
        resp = self.client.get(reverse("subscription-plan-list"))
        names = [p["name"] for p in resp.data["data"]]
        self.assertEqual(names, ["Monthly", "6-Month", "Yearly"])

    def test_inactive_plan_hidden_from_public(self):
        """Inactive plans are not shown to unauthenticated users."""
        SubscriptionPlan.objects.filter(slug="monthly").update(is_active=False)
        resp = self.client.get(reverse("subscription-plan-list"))
        slugs = [p["slug"] for p in resp.data["data"]]
        self.assertNotIn("monthly", slugs)

    def test_plan_total_price_is_price_times_months(self):
        """total_price = price_per_month × duration_months."""
        resp = self.client.get(reverse("subscription-plan-list"))
        yearly = next(p for p in resp.data["data"] if p["slug"] == "yearly")
        self.assertEqual(yearly["total_price"], 22000 * 12)

    def test_extra_store_total_price_correct(self):
        """extra_store_price_total = extra_price × duration_months."""
        resp = self.client.get(reverse("subscription-plan-list"))
        yearly = next(p for p in resp.data["data"] if p["slug"] == "yearly")
        self.assertEqual(yearly["extra_store_price_total"], 12000 * 12)


# ── StoreLimitView ────────────────────────────────────────────────────────────

class StoreLimitTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def _setup_owner(self, max_stores=3, extra_stores_in_sub=0):
        plan = make_plan()
        org, store, owner, sub = make_org_with_owner(max_stores=max_stores)
        if extra_stores_in_sub:
            sub.extra_stores = extra_stores_in_sub
            sub.save()
            org.max_stores = plan.included_stores + extra_stores_in_sub
            org.save()
        login(self.client, "0712000001")
        return org, store, owner, sub, plan

    def test_can_add_when_below_limit(self):
        """Returns can_add_store=True when store count < max."""
        self._setup_owner(max_stores=3)  # 1 store exists, max is 3
        resp = self.client.get(reverse("store-limit"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertTrue(data["can_add_store"])
        self.assertEqual(data["current_active_stores"], 1)
        self.assertEqual(data["max_stores_allowed"], 3)
        self.assertEqual(data["remaining_slots"], 2)

    def test_cannot_add_when_at_limit(self):
        """Returns can_add_store=False when store count == max."""
        org, _, owner, sub, _ = self._setup_owner(max_stores=1)  # 1 store, max=1
        resp = self.client.get(reverse("store-limit"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertFalse(data["can_add_store"])
        self.assertEqual(data["remaining_slots"], 0)
        self.assertIn("12,000", data["message"])

    def test_store_limit_shows_correct_extra_price_from_plan(self):
        """extra_store_price_per_month comes from the active plan when present."""
        plan = make_plan(extra_price=15000)
        org, store, owner, sub = make_org_with_owner()
        sub.plan = plan
        sub.save()
        login(self.client, "0712000001")
        resp = self.client.get(reverse("store-limit"))
        self.assertEqual(resp.data["data"]["extra_store_price_per_month"], 15000)

    def test_unauthenticated_denied(self):
        """Unauthenticated request is rejected."""
        resp = APIClient().get(reverse("store-limit"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── StoreViewSet.create with limit enforcement ────────────────────────────────

class StoreCreateLimitTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def _owner_client(self, max_stores=3):
        org, store, owner, sub = make_org_with_owner(max_stores=max_stores)
        login(self.client, "0712000001")
        return org, store, owner

    def test_owner_can_create_store_within_limit(self):
        """POST /stores/ succeeds when below max_stores."""
        org, _, _ = self._owner_client(max_stores=3)  # 1 store exists (Main Store)
        resp = self.client.post(reverse("store-list"), {
            "name": "Branch 2", "area": "Mwenge",
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        # Verify the store was actually created with correct attributes
        new_store = Store.objects.get(name="Branch 2")
        self.assertTrue(new_store.is_active)
        self.assertEqual(str(new_store.organisation_id), str(org.id))

    def test_store_creation_blocked_at_limit(self):
        """POST /stores/ returns 403 when at max_stores (1 store, max=1)."""
        org, _, _ = self._owner_client(max_stores=1)  # already at limit
        resp = self.client.post(reverse("store-list"), {
            "name": "Extra Branch", "area": "Kariakoo",
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(resp.data["success"])
        errors = resp.data["errors"]
        self.assertFalse(errors["can_add_store"])
        self.assertEqual(errors["max_stores_allowed"], 1)
        self.assertIn("extra_store_price_per_month", errors)
        self.assertEqual(errors["action"], "contact_support")
        # Confirm no second store was created
        self.assertFalse(Store.objects.filter(name="Extra Branch").exists())

    def test_deactivated_store_does_not_count_toward_limit(self):
        """Inactive stores are not counted against max_stores."""
        org, first_store, _ = self._owner_client(max_stores=2)
        first_store.is_active = False
        first_store.save()
        # 0 active stores out of max 2 → allowed
        resp = self.client.post(reverse("store-list"), {
            "name": "New Active Store", "area": "Mwenge",
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Store.objects.filter(name="New Active Store").exists())

    def test_adding_up_to_max_stores_all_succeed(self):
        """Owner can fill all store slots; the (n+1)th is blocked."""
        org, _, _ = self._owner_client(max_stores=3)  # 1 store (Main Store) already
        # Slots 2 and 3 should succeed
        for i, area in enumerate(["Mwenge", "Ubungo"], start=2):
            resp = self.client.post(reverse("store-list"), {
                "name": f"Branch {i}", "area": area,
            })
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED,
                             f"Branch {i} should have been created but got {resp.status_code}: {resp.data}")
        # Now at 3/3 — Branch 4 should be blocked
        resp = self.client.post(reverse("store-list"), {
            "name": "Branch 4", "area": "Temeke",
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN,
                         f"Branch 4 should be blocked but got {resp.status_code}: {resp.data}")
        self.assertFalse(Store.objects.filter(name="Branch 4").exists())


# ── Admin activates subscription → max_stores syncs ──────────────────────────

class SubscriptionActivationTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin  = make_admin()
        login(self.client, "0799000001", "admin123!")

    def test_activate_subscription_syncs_max_stores(self):
        """Activating a subscription updates org.max_stores to plan.included_stores."""
        plan = make_plan(included_stores=3)
        org, _, _, sub = make_org_with_owner(phone="0712000002", max_stores=3)
        sub.plan   = plan
        sub.status = Subscription.STATUS_PENDING
        sub.save()

        resp = self.client.post(
            reverse("subscription-activate", args=[sub.id]),
            {"status": "active", "amount_paid": 25000, "payment_reference": "MPESA123"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        org.refresh_from_db()
        sub.refresh_from_db()
        self.assertEqual(sub.status, "active")
        self.assertEqual(org.max_stores, 3)   # plan.included_stores=3
        self.assertEqual(org.plan, "pro")

    def test_activate_trial_sets_org_plan_free(self):
        """Activating as trial keeps org.plan='free'."""
        org, _, _, sub = make_org_with_owner(phone="0712000003")
        resp = self.client.post(
            reverse("subscription-activate", args=[sub.id]),
            {"status": "trial", "amount_paid": 10000},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        org.refresh_from_db()
        self.assertEqual(org.plan, "free")


# ── Admin grants extra stores → org.max_stores syncs ─────────────────────────

class ExtraStoreGrantTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin  = make_admin()
        login(self.client, "0799000001", "admin123!")

    def test_granting_extra_store_increases_max_stores(self):
        """PATCH /subscriptions/all/{id}/extra-stores/ bumps org.max_stores."""
        plan = make_plan(included_stores=3, extra_price=12000)
        org, _, _, sub = make_org_with_owner(phone="0712000002", max_stores=3)
        sub.plan = plan
        sub.save()

        resp = self.client.patch(
            reverse("subscription-extra-stores", args=[sub.id]),
            {"extra_stores": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        org.refresh_from_db()
        sub.refresh_from_db()
        self.assertEqual(sub.extra_stores, 1)
        self.assertEqual(org.max_stores, 4)   # 3 included + 1 extra
        self.assertEqual(resp.data["data"]["org_max_stores_now"], 4)

    def test_granting_multiple_extra_stores(self):
        """PATCH extra_stores=3 → max_stores = included(3) + 3 = 6."""
        plan = make_plan(included_stores=3)
        org, _, _, sub = make_org_with_owner(phone="0712000003", max_stores=3)
        sub.plan = plan
        sub.save()

        resp = self.client.patch(
            reverse("subscription-extra-stores", args=[sub.id]),
            {"extra_stores": 3},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        org.refresh_from_db()
        self.assertEqual(org.max_stores, 6)

    def test_reducing_extra_stores_reduces_max_stores(self):
        """Admin can reduce extra stores (e.g. owner stops paying for extras)."""
        plan = make_plan(included_stores=3)
        org, _, _, sub = make_org_with_owner(phone="0712000004", max_stores=5)
        sub.plan         = plan
        sub.extra_stores = 2
        sub.save()

        resp = self.client.patch(
            reverse("subscription-extra-stores", args=[sub.id]),
            {"extra_stores": 0},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        org.refresh_from_db()
        self.assertEqual(org.max_stores, 3)

    def test_non_admin_cannot_grant_extra_stores(self):
        """Owner cannot grant themselves extra stores."""
        _, _, _, sub = make_org_with_owner(phone="0712000005")
        owner_client = APIClient()
        login(owner_client, "0712000005")
        resp = owner_client.patch(
            reverse("subscription-extra-stores", args=[sub.id]),
            {"extra_stores": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ── Subscription model properties ─────────────────────────────────────────────

class SubscriptionModelTests(TestCase):

    def setUp(self):
        self.plan = make_plan(included_stores=3, extra_price=12000,
                              price=25000, months=1)
        org = Organisation.objects.create(name="Org", max_stores=3)
        today = date.today()
        self.sub = Subscription.objects.create(
            organisation=org,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            start_date=today,
            end_date=today + timedelta(days=30),
            is_trial=False,
            extra_stores=0,
        )

    def test_max_stores_allowed_base(self):
        """max_stores_allowed = plan.included_stores + extra_stores."""
        self.assertEqual(self.sub.max_stores_allowed, 3)

    def test_max_stores_allowed_with_extras(self):
        """max_stores_allowed increases with extra_stores."""
        self.sub.extra_stores = 2
        self.sub.save()
        self.assertEqual(self.sub.max_stores_allowed, 5)

    def test_is_active_now_true_for_active_within_dates(self):
        """is_active_now is True when status=active and end_date >= today."""
        self.assertTrue(self.sub.is_active_now)

    def test_is_active_now_false_when_expired(self):
        """is_active_now is False when end_date is in the past."""
        self.sub.end_date = date.today() - timedelta(days=1)
        self.sub.save()
        self.assertFalse(self.sub.is_active_now)

    def test_days_remaining_positive_for_active_sub(self):
        """days_remaining > 0 for a future end_date."""
        self.assertGreater(self.sub.days_remaining, 0)

    def test_total_amount_due_monthly(self):
        """Monthly plan total = price_per_month × 1."""
        self.assertEqual(self.sub.total_amount_due, 25000)

    def test_total_amount_due_with_extra_stores(self):
        """Total due includes extra stores for the full cycle."""
        self.sub.extra_stores = 1
        self.sub.save()
        # 25000 + (12000 × 1 × 1 month)
        self.assertEqual(self.sub.total_amount_due, 25000 + 12000)

    def test_plan_total_price_yearly(self):
        """Yearly plan total_price = 22000 × 12."""
        plan = make_plan("Yearly", "yearly2", 22000, 12)
        self.assertEqual(plan.total_price, 22000 * 12)

    def test_plan_extra_store_price_total_yearly(self):
        """Yearly extra store total = 12000 × 12."""
        plan = make_plan("Yearly", "yearly3", 22000, 12, extra_price=12000)
        self.assertEqual(plan.extra_store_price_total, 12000 * 12)
