# Ziada Backend — Updates Today (2026-06-03)

This file documents all backend changes made today. The UI team should read this
before building or updating any auth, registration, profile, or subscription screens.

---

## 1. Authentication — Phone-Based Login (BREAKING CHANGE)

**Previous:** Login used `username` + `password`
**Now:** Login uses `phone` + `password`

### POST `/api/v1/auth/login/`

**Request:**
```json
{
  "phone": "0712345678",
  "password": "yourpassword"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Logged in successfully.",
  "data": {
    "access": "<JWT access token>",
    "refresh": "<JWT refresh token>",
    "user": { ... },
    "subscription": {
      "status": "trial | active | expired | pending_payment | cancelled",
      "is_trial": true,
      "is_active_now": true,
      "days_remaining": 6,
      "end_date": "2026-06-10"
    }
  }
}
```

**Notes:**
- Phone must be exactly 10 digits (e.g. `0712345678`)
- Returns `401` for invalid credentials
- Returns `subscription` block so the UI can immediately gate access or show trial banners

---

## 2. Self-Registration — New Endpoint

### POST `/api/v1/auth/register/`

Creates: Organisation + main Store + owner User + trial Subscription (atomically).
Also seeds pre-configured product categories based on business type.

**Request:**
```json
{
  "full_name":       "Hamisi Mwakapaga",
  "phone":           "0712345678",
  "password":        "StrongPass123!",
  "confirm_password":"StrongPass123!",
  "email":           "hamisi@dukakuu.co.tz",  // optional
  "main_shop_name":  "Duka Kuu",
  "business_type":   "retail",                // pharmacy | retail | wholesale
  "region":          "Dar es Salaam"
}
```

**Response (201 Created):**
```json
{
  "success": true,
  "message": "Welcome to Ziada! Your account has been created. Please pay 10,000 TZS to activate your 7-day trial.",
  "data": {
    "user":  { ... },
    "organisation": { ... },
    "subscription": {
      "id":           "<uuid>",
      "status":       "pending_payment",
      "is_trial":     true,
      "end_date":     "2026-06-10",
      "trial_fee":    10000,
      "days_remaining": 7
    },
    "access":  "<JWT access token>",
    "refresh": "<JWT refresh token>"
  }
}
```

**Validation rules:**
- `phone`: exactly 10 digits, must be unique across all users
- `email`: optional, must be unique if provided
- `password` / `confirm_password`: must match, Django password strength rules apply
- `business_type`: one of `pharmacy`, `retail`, `wholesale`
- `region`: must be a valid Tanzania region (see list below)

**Tanzania regions (valid values for `region`):**
Arusha, Dar es Salaam, Dodoma, Geita, Iringa, Kagera, Katavi, Kigoma,
Kilimanjaro, Lindi, Manyara, Mara, Mbeya, Morogoro, Mtwara, Mwanza,
Njombe, Pemba North, Pemba South, Pwani, Rukwa, Ruvuma, Shinyanga,
Simiyu, Singida, Songwe, Tabora, Tanga, Unguja North, Unguja South, Unguja West

**Business type → auto-seeded categories:**

| Type       | Categories seeded automatically |
|------------|---------------------------------|
| pharmacy   | Prescription Drugs, OTC Medications, Vitamins & Supplements, Medical Supplies, Personal Care, Baby Products, Surgical Items, Herbal Medicine |
| retail     | Grocery, Beverages, Household, Personal Care, Snacks, Electronics, Clothing, Stationery, Frozen Foods, Cleaning Supplies |
| wholesale  | Food Products, Beverages, Cleaning Supplies, Personal Care, Agricultural, Industrial Goods, Packaging, Stationery |

---

## 3. User Roles (BREAKING CHANGE)

**Previous roles:** `admin`, `manager`, `cashier`
**New roles:** `admin`, `owner`, `staff`

| Role    | Who                  | What they can do |
|---------|----------------------|------------------|
| `admin` | Cameltech staff      | Full platform access. Manage subscriptions, all orgs. |
| `owner` | Registered business owner | Manage their org, all stores, all staff, reports, settings. |
| `staff` | Store employee       | POS, transactions, credits. Permissions set by owner. |

**Permission class map (for views):**

| Old class             | New class (alias kept) | Who can access |
|-----------------------|------------------------|----------------|
| `IsOrganisationAdmin` | `IsSystemAdmin`        | `admin` only |
| `IsStoreManager`      | `IsOwner`              | `admin` + `owner` |
| `IsStoreCashier`      | `IsStoreStaff`         | all authenticated roles |

**Old names are aliased** — existing views still work, but new views use the new names.

---

## 4. User Model — New Fields

The User model now exposes these additional fields in all responses:

| Field              | Type    | Description |
|--------------------|---------|-------------|
| `phone`            | string  | 10-digit login phone (unique) |
| `is_phone_verified`| boolean | False until owner confirms via OTP (reminder shown on profile) |
| `is_email_verified`| boolean | False until owner confirms email (reminder shown on profile) |
| `organisation`     | UUID    | Direct org FK for owners |

**Removed from responses:** `username` (internal implementation detail — now equals phone)

**Profile page should show reminders when:**
- `is_phone_verified == false` → "Please verify your phone number"
- `is_email_verified == false` AND `email != null` → "Please verify your email"

---

## 5. GET `/api/v1/accounts/me/` — Updated Response

Now returns verification status and subscription alongside user data:

```json
{
  "success": true,
  "data": {
    "user": { ... },
    "subscription": {
      "status":        "trial | active | expired | pending_payment | cancelled",
      "is_trial":      true,
      "is_active_now": true,
      "days_remaining": 6,
      "end_date":      "2026-06-10"
    },
    "verification": {
      "phone_verified": false,
      "email_verified": false
    }
  }
}
```

---

## 6. Organisation Model — New Fields

| Field           | Type   | Values / Notes |
|-----------------|--------|----------------|
| `business_type` | string | `pharmacy`, `retail`, `wholesale` |
| `region`        | string | Tanzania region name |
| `max_stores`    | int    | Default 3. Increases when extra stores are purchased. |

These are returned in `GET /api/v1/accounts/organisation/`.

---

## 7. Store Model — New Fields

| Field          | Type    | Notes |
|----------------|---------|-------|
| `is_main_store`| boolean | True for the first store created at registration |

---

## 8. Subscription System — New App

Base URL: `/api/v1/subscriptions/`

### Pricing Plans (public — show on registration/upgrade screens)

#### GET `/api/v1/subscriptions/plans/`

Returns all active plans. No auth required.

```json
{
  "success": true,
  "data": [
    {
      "id": "...",
      "name": "Monthly",
      "slug": "monthly",
      "price_per_month": 25000,
      "duration_months": 1,
      "total_price": 25000,
      "included_stores": 3,
      "extra_store_price_per_month": 12000,
      "extra_store_price_total": 12000
    },
    {
      "name": "6-Month Package",
      "slug": "half-yearly",
      "price_per_month": 23000,
      "duration_months": 6,
      "total_price": 138000,
      "included_stores": 3,
      "extra_store_price_per_month": 12000,
      "extra_store_price_total": 72000
    },
    {
      "name": "Yearly Package",
      "slug": "yearly",
      "price_per_month": 22000,
      "duration_months": 12,
      "total_price": 264000,
      "included_stores": 3,
      "extra_store_price_per_month": 12000,
      "extra_store_price_total": 144000
    }
  ]
}
```

### Owner Subscription Status

#### GET `/api/v1/subscriptions/my-subscription/`

Auth required. Returns the owner's current subscription.

```json
{
  "success": true,
  "data": {
    "id": "...",
    "status": "pending_payment",
    "is_trial": true,
    "trial_fee": 10000,
    "start_date": "2026-06-03",
    "end_date": "2026-06-10",
    "is_active_now": false,
    "days_remaining": 7,
    "max_stores_allowed": 3,
    "total_amount_due": 10000,
    "payment_reference": "",
    "extra_stores": 0,
    "plan_detail": null
  }
}
```

### Subscription Statuses

| Status            | Meaning |
|-------------------|---------|
| `pending_payment` | Created but payment not confirmed. Trial not yet activated. |
| `trial`           | Payment confirmed. 7-day trial active. |
| `active`          | Paid subscription active. |
| `expired`         | Subscription end_date passed. Access blocked. |
| `cancelled`       | Manually cancelled by admin. |

### UI Gating Rules

- `is_active_now == false` → Block POS access, show payment required screen
- `status == "pending_payment"` → Show "pay 10,000 TZS to start trial" message
- `status == "trial"` → Show trial banner with days_remaining countdown
- `days_remaining <= 3` → Show urgent renewal warning
- `status == "expired"` → Show subscription expired screen with upgrade options

---

## 9. Admin Panel — Subscription Management

Cameltech staff use the Django admin panel at `/admin/` to:
- Create and price subscription plans (monthly, 6-month, yearly, extras)
- View all organisations and their subscriptions
- Confirm payment received and activate subscriptions
- Add extra store slots to a subscription

**API endpoints for Cameltech admin (role=admin):**
- `GET /api/v1/subscriptions/all/` — list all subscriptions
- `POST /api/v1/subscriptions/all/{id}/activate/` — confirm payment + activate
- `PATCH /api/v1/subscriptions/all/{id}/extra-stores/` — add extra stores

---

## 10. Store Creation — Max Stores Enforcement

`POST /api/v1/accounts/stores/` now validates against `organisation.max_stores`.

- Default: 3 stores included in base package
- If limit reached: returns `403` with message:
  > "You have reached your maximum store limit (3). Purchase an extra store slot to add more branches."

---

## 11. Seeded Plan Data (run after migrations)

After running `python manage.py migrate`, create the initial plans in Django admin
or via the API (as an admin user):

```
POST /api/v1/subscriptions/plans/
{ "name": "Monthly", "slug": "monthly", "price_per_month": 25000, "duration_months": 1, "included_stores": 3, "extra_store_price_per_month": 12000, "sort_order": 1, "is_active": true }

POST /api/v1/subscriptions/plans/
{ "name": "6-Month Package", "slug": "half-yearly", "price_per_month": 23000, "duration_months": 6, "included_stores": 3, "extra_store_price_per_month": 12000, "sort_order": 2, "is_active": true }

POST /api/v1/subscriptions/plans/
{ "name": "Yearly Package", "slug": "yearly", "price_per_month": 22000, "duration_months": 12, "included_stores": 3, "extra_store_price_per_month": 12000, "sort_order": 3, "is_active": true }
```

---

## 12. Migrations Required

After pulling this update, run:
```bash
cd backend
python manage.py makemigrations accounts subscriptions
python manage.py migrate
```

**What the migrations will create/change:**
- `accounts_user`: new fields `phone` (unique), `organisation` FK, `is_phone_verified`, `is_email_verified`; role choices updated to admin/owner/staff
- `accounts_organisation`: new fields `business_type`, `region`, `max_stores`
- `accounts_store`: new field `is_main_store`
- `subscriptions_subscriptionplan`: new table
- `subscriptions_subscription`: new table

---

---

## 14. Store Limit System (Update 2)

### GET `/api/v1/subscriptions/store-limit/` — new endpoint

Returns whether the owner can add another store and full pricing info for the UI to gate the "Add Store" button.

```json
{
  "success": true,
  "data": {
    "can_add_store": false,
    "current_active_stores": 3,
    "max_stores_allowed": 3,
    "remaining_slots": 0,
    "extra_store_price_per_month": 12000,
    "subscription_status": "active",
    "subscription_is_active": true,
    "days_remaining": 18,
    "message": "You have reached your 3-store limit. Additional stores cost 12,000 TZS/month. Contact Ziada support to purchase more store slots."
  }
}
```

### POST `/api/v1/stores/` — improved 403 response

When at limit, returns machine-readable error with pricing so the UI can display the right CTA:

```json
{
  "success": false,
  "message": "Store limit reached (3/3). Additional stores cost 12,000 TZS/month. Contact Ziada support to purchase more store slots.",
  "errors": {
    "can_add_store": false,
    "current_active_stores": 3,
    "max_stores_allowed": 3,
    "extra_store_price_per_month": 12000,
    "action": "contact_support"
  }
}
```

### `max_stores` sync is now guaranteed

`organisation.max_stores` is automatically updated whenever:
- Admin activates a subscription
- Admin grants extra store slots

No manual DB editing required.

### BooleanField fix in StoreWriteSerializer

Removed `is_active` from `StoreWriteSerializer` fields — DRF's BooleanField defaults to `False` when absent from multipart form data, causing silently inactive stores. New stores are always created active; deactivation uses the DELETE endpoint.

---

## 15. Files Changed (Update 2)

| File | Change |
|------|--------|
| `apps/subscriptions/api/views.py` | New `StoreLimitView`, fixed `activate()` to sync `max_stores`, improved `extra_stores()` |
| `apps/subscriptions/api/urls.py` | Added `/store-limit/` endpoint |
| `apps/stores/api/views.py` | Added store limit check to `create()`, fixed `_get_org()` to use `get_organisation` |
| `apps/stores/api/serializers.py` | Removed `is_active` from `StoreWriteSerializer` to prevent BooleanField default-to-False bug |
| `apps/accounts/api/views.py` | Improved limit error response with machine-readable pricing data |
| `apps/accounts/api/urls.py` | Renamed accounts store router basename to `account-store` to avoid URL name collision |
| `apps/subscriptions/tests/test_subscriptions.py` | **NEW** — 28 tests covering store limit, subscription activation, extra store grants |
| `docs/AUTH_FLOW.md` | **NEW** — Auth flow documentation |
| `docs/STORE_MANAGEMENT.md` | **NEW** — Store limits and extra store process |
| `docs/SUBSCRIPTION_SYSTEM.md` | **NEW** — Subscription lifecycle, pricing, admin panel |
| `docs/API_REFERENCE.md` | **NEW** — Complete API endpoint reference |

---

## 13. Files Changed Today

| File | Change |
|------|--------|
| `apps/accounts/models.py` | Roles, phone login, org/store fields, verification flags |
| `apps/accounts/tanzania.py` | **NEW** — Tanzania regions, business type presets, category seeder |
| `apps/accounts/api/serializers.py` | RegistrationSerializer, PhoneLoginSerializer, UserSerializer updated |
| `apps/accounts/api/views.py` | RegisterView, PhoneLoginView, updated MeView/OrgView/AICredits |
| `apps/accounts/api/auth_urls.py` | `/register/` + `/login/` replaced with new phone-based views |
| `apps/accounts/api/urls.py` | No structure change; updated imports |
| `apps/core/permissions.py` | New: IsSystemAdmin, IsOwner, IsStoreStaff (old names aliased) |
| `apps/subscriptions/` | **NEW** — full subscriptions app (models, admin, API) |
| `ziada/settings/base.py` | Added `apps.subscriptions` to INSTALLED_APPS |
| `ziada/urls.py` | Added `/api/v1/subscriptions/` route |
| `backend/updates-today.md` | **THIS FILE** |
