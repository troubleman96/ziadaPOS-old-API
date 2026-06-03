# Authentication & User Roles

## Overview

Ziada uses **phone number + password** authentication (not username). All users log in with their Tanzanian phone number (10 digits, e.g. `0712345678`).

---

## Registration

**Endpoint:** `POST /api/v1/auth/register/`  
**Auth required:** No

Registering creates **four records atomically** in one database transaction:
1. `Organisation` — the business entity
2. `Store` — the first (main) store
3. `User` — the owner account
4. `Subscription` — a 7-day trial (status: `pending_payment`)

Product categories are automatically seeded based on `business_type`.

### Request body

```json
{
  "full_name":        "Hamisi Mwakapaga",
  "phone":            "0712345678",
  "password":         "StrongPass123!",
  "confirm_password": "StrongPass123!",
  "email":            "hamisi@duka.co.tz",
  "main_shop_name":   "Duka Kuu",
  "business_type":    "retail",
  "region":           "Dar es Salaam"
}
```

| Field | Required | Validation |
|-------|----------|------------|
| `full_name` | Yes | Any string |
| `phone` | Yes | Exactly 10 digits. Must be unique globally. |
| `password` | Yes | Django password strength rules |
| `confirm_password` | Yes | Must match `password` |
| `email` | No | Valid email. Must be unique if provided. |
| `main_shop_name` | Yes | Becomes Organisation name and main Store name |
| `business_type` | Yes | `pharmacy`, `retail`, or `wholesale` |
| `region` | Yes | Any of the 31 Tanzania administrative regions |

### Response (201 Created)

```json
{
  "success": true,
  "message": "Welcome to Ziada! Your account has been created. Please pay 10,000 TZS to activate your 7-day trial.",
  "data": {
    "user":         { ...UserSerializer... },
    "organisation": { ...OrganisationSerializer... },
    "subscription": {
      "id":             "uuid",
      "status":         "pending_payment",
      "is_trial":       true,
      "end_date":       "2026-06-10",
      "trial_fee":      10000,
      "days_remaining": 7
    },
    "access":  "<JWT access token>",
    "refresh": "<JWT refresh token>"
  }
}
```

User is **automatically logged in** after registration — no separate login call needed.

---

## Login

**Endpoint:** `POST /api/v1/auth/login/`  
**Auth required:** No

```json
{ "phone": "0712345678", "password": "StrongPass123!" }
```

### Response (200 OK)

```json
{
  "success": true,
  "message": "Logged in successfully.",
  "data": {
    "access":  "<JWT access token>",
    "refresh": "<JWT refresh token>",
    "user":    { ...UserSerializer... },
    "subscription": {
      "status":        "trial",
      "is_trial":      true,
      "is_active_now": true,
      "days_remaining": 5,
      "end_date":      "2026-06-10"
    }
  }
}
```

### Errors

| HTTP | Condition |
|------|-----------|
| 401 | Wrong phone or password |
| 401 | Account deactivated |

---

## Token refresh

**Endpoint:** `POST /api/v1/auth/refresh/`

```json
{ "refresh": "<refresh token>" }
```

Returns `{ "access": "<new access token>" }`.

---

## Roles

| Role | Who | What they can do |
|------|-----|-----------------|
| `admin` | Cameltech staff | Full platform access. Manage subscription plans, activate subscriptions, view all orgs. |
| `owner` | Registered business owner | Manage their organisation's stores, staff, inventory, reports, and settings. |
| `staff` | Store employee | POS operations (sales, credits, customers) within their assigned store. Permissions set by owner. |

### Permission mapping (for API views)

| Class | Roles allowed | Used for |
|-------|--------------|---------|
| `IsSystemAdmin` | `admin` only | Subscription plan management, platform admin |
| `IsOwner` | `admin`, `owner` | Store creation, staff management, reports |
| `IsStoreStaff` | `admin`, `owner`, `staff` | POS, transactions, credits, customers |

**Backward-compatible aliases:** `IsOrganisationAdmin` → `IsSystemAdmin`, `IsStoreManager` → `IsOwner`, `IsStoreCashier` → `IsStoreStaff`

---

## User model: key fields

| Field | Type | Notes |
|-------|------|-------|
| `phone` | char(10) | Unique. The login field. |
| `email` | email | Optional. Unique when provided. |
| `role` | choice | `admin` / `owner` / `staff` |
| `organisation` | FK | Set for owners (direct org link) |
| `store` | FK | Set for all users (primary store) |
| `is_phone_verified` | bool | False until owner verifies via OTP |
| `is_email_verified` | bool | False until owner confirms email |
| `can_refund` | bool | Owner-configurable per staff member |
| `can_discount` | bool | Owner-configurable per staff member |
| `can_view_reports` | bool | Owner-configurable per staff member |

---

## Verification reminders

The profile page (`GET /api/v1/accounts/me/`) returns a `verification` object:

```json
{
  "verification": {
    "phone_verified": false,
    "email_verified": false
  }
}
```

Show reminder banners when:
- `phone_verified == false` → "Please verify your phone number"
- `email_verified == false` AND `email != null` → "Please verify your email"

Verification endpoints (OTP) will be added in a future sprint.

---

## Tanzania regions (valid values for `region`)

Arusha, Dar es Salaam, Dodoma, Geita, Iringa, Kagera, Katavi, Kigoma, Kilimanjaro, Lindi, Manyara, Mara, Mbeya, Morogoro, Mtwara, Mwanza, Njombe, Pemba North, Pemba South, Pwani, Rukwa, Ruvuma, Shinyanga, Simiyu, Singida, Songwe, Tabora, Tanga, Unguja North, Unguja South, Unguja West

## Business types & seeded categories

| Type | `business_type` value | Auto-seeded categories |
|------|-----------------------|----------------------|
| Pharmacy | `pharmacy` | Prescription Drugs, OTC Medications, Vitamins & Supplements, Medical Supplies, Personal Care, Baby Products, Surgical Items, Herbal Medicine |
| Retail Shop | `retail` | Grocery, Beverages, Household, Personal Care, Snacks, Electronics, Clothing, Stationery, Frozen Foods, Cleaning Supplies |
| Wholesale | `wholesale` | Food Products, Beverages, Cleaning Supplies, Personal Care, Agricultural, Industrial Goods, Packaging, Stationery |
