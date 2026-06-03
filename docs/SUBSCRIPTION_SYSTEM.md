# Subscription System

## Pricing (configured in Django admin)

All amounts are **Tanzanian Shillings (TZS)**, stored as integers. No decimals.

| Plan | Monthly price | Duration | Total | Stores included |
|------|--------------|----------|-------|-----------------|
| **Monthly** | 25,000 TZS | 1 month | 25,000 TZS | 3 |
| **6-Month** | 23,000 TZS | 6 months | 138,000 TZS | 3 |
| **Yearly** | 22,000 TZS | 12 months | 264,000 TZS | 3 |
| **Extra store** | 12,000 TZS/month | Matches plan | — | +1 per purchase |

**Trial:** 10,000 TZS one-time fee for 7 days of access (all features, all 3 store slots).

---

## Subscription lifecycle

```
REGISTRATION
     │
     ▼
status = "pending_payment"   ← trial subscription created (not yet activated)
     │
     │   Owner pays 10,000 TZS trial fee via M-Pesa / bank
     │   Owner notifies Cameltech (WhatsApp / phone)
     │
     ▼
Admin activates: status = "trial"  ← 7-day trial clock starts
     │
     │   (7 days pass OR owner upgrades)
     │
     ▼
Owner selects plan, pays              ← admin creates new subscription
     │
     ▼
Admin activates: status = "active"   ← full subscription
     │
     │   (end_date passes)
     │
     ▼
status = "expired"                   ← POS access blocked
```

---

## Status reference

| Status | Meaning | Access granted |
|--------|---------|---------------|
| `pending_payment` | Trial created, payment not confirmed | No (blocked) |
| `trial` | 7-day trial, payment confirmed | Yes |
| `active` | Paid subscription, payment confirmed | Yes |
| `expired` | end_date passed | No (blocked) |
| `cancelled` | Manually cancelled by admin | No |

`is_active_now = (status in ["trial", "active"]) AND (end_date >= today)`

---

## UI gating rules

On login and on each app load, check `subscription` in the login/me response:

```
if is_active_now == false:
  if status == "pending_payment" → Show "Pay 10,000 TZS to start your 7-day trial"
  if status == "expired"         → Show "Subscription expired. Choose a plan to continue."
  if status == "cancelled"       → Show "Account cancelled. Contact support."
  Block all POS, inventory, and management screens.

if is_active_now == true:
  if status == "trial" AND days_remaining <= 3 → Show urgent "Trial ending soon" banner
  if status == "active" AND days_remaining <= 7 → Show "Renew soon" warning banner
  Allow full access.
```

---

## API endpoints

### Public (no auth required)

#### List pricing plans

`GET /api/v1/subscriptions/plans/`

```json
{
  "success": true,
  "data": [
    {
      "id": "uuid",
      "name": "Monthly",
      "slug": "monthly",
      "description": "",
      "price_per_month": 25000,
      "duration_months": 1,
      "total_price": 25000,
      "included_stores": 3,
      "extra_store_price_per_month": 12000,
      "extra_store_price_total": 12000,
      "is_active": true,
      "sort_order": 1
    },
    {
      "name": "6-Month Package",
      "slug": "half-yearly",
      "price_per_month": 23000,
      "duration_months": 6,
      "total_price": 138000,
      "extra_store_price_total": 72000,
      ...
    },
    {
      "name": "Yearly Package",
      "slug": "yearly",
      "price_per_month": 22000,
      "duration_months": 12,
      "total_price": 264000,
      "extra_store_price_total": 144000,
      ...
    }
  ]
}
```

---

### Owner endpoints (auth required, role: owner or admin)

#### Get my subscription

`GET /api/v1/subscriptions/my-subscription/`

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "organisation": "uuid",
    "organisation_name": "Duka Kuu",
    "plan": "uuid",
    "plan_detail": { ...SubscriptionPlanSerializer... },
    "status": "trial",
    "start_date": "2026-06-03",
    "end_date": "2026-06-10",
    "is_trial": true,
    "trial_fee": 10000,
    "extra_stores": 0,
    "amount_paid": 0,
    "payment_reference": "",
    "payment_date": null,
    "is_active_now": false,
    "days_remaining": 7,
    "max_stores_allowed": 3,
    "total_amount_due": 10000,
    "notes": "",
    "created_at": "...",
    "updated_at": "..."
  }
}
```

#### Check store limit

`GET /api/v1/subscriptions/store-limit/`

See [STORE_MANAGEMENT.md](STORE_MANAGEMENT.md) for full response spec.

---

### Admin endpoints (auth required, role: admin only)

#### List all subscriptions

`GET /api/v1/subscriptions/all/`

Optional query params: `?status=trial|active|expired|pending_payment|cancelled`, `?organisation=<uuid>`

#### Activate / confirm payment

`POST /api/v1/subscriptions/all/{id}/activate/`

```json
{
  "status":            "trial",
  "amount_paid":       10000,
  "payment_reference": "MPESA-BG7JK2",
  "payment_date":      "2026-06-03",
  "notes":             "Payment confirmed via WhatsApp"
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `status` | Yes | `trial` or `active` |
| `amount_paid` | No | TZS integer |
| `payment_reference` | No | M-Pesa code, bank ref |
| `payment_date` | No | Defaults to today |
| `notes` | No | Internal note |

After activation:
- `organisation.plan` → `"free"` (trial) or `"pro"` (active)
- `organisation.max_stores` → synced from `plan.included_stores + extra_stores`

#### Grant extra store slots

`PATCH /api/v1/subscriptions/all/{id}/extra-stores/`

```json
{ "extra_stores": 1 }
```

Effect: `organisation.max_stores = plan.included_stores + extra_stores`

---

## Admin panel (Django)

Access at `/admin/` with a system admin account.

### Create / update pricing plans

**Subscriptions → Subscription Plans**

| Field | Example | Notes |
|-------|---------|-------|
| Name | Monthly | Display name |
| Slug | monthly | URL-safe, used in filters |
| Price per month | 25000 | TZS, no decimals |
| Duration months | 1 | 1=monthly, 6=half-yearly, 12=yearly |
| Included stores | 3 | Stores bundled in base price |
| Extra store price/month | 12000 | Per additional store, per month |
| Is active | ✓ | Uncheck to hide from pricing page |
| Sort order | 1 | Lower = shown first |

### View and manage subscriptions

**Subscriptions → Subscriptions**

From here you can:
- See all organisations and their subscription status
- Activate a subscription after confirming payment
- Add extra store slots
- Check `is_active_now`, `days_remaining`, `total_amount_due`

---

## Seeding initial plans

After running migrations for the first time, create the three standard plans. You can do this via:

**Django admin** (easiest) or **API**:

```bash
# Get an admin JWT token first, then:

curl -X POST http://localhost:8000/api/v1/subscriptions/plans/ \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Monthly","slug":"monthly","price_per_month":25000,"duration_months":1,"included_stores":3,"extra_store_price_per_month":12000,"sort_order":1}'

curl -X POST http://localhost:8000/api/v1/subscriptions/plans/ \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"6-Month Package","slug":"half-yearly","price_per_month":23000,"duration_months":6,"included_stores":3,"extra_store_price_per_month":12000,"sort_order":2}'

curl -X POST http://localhost:8000/api/v1/subscriptions/plans/ \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Yearly Package","slug":"yearly","price_per_month":22000,"duration_months":12,"included_stores":3,"extra_store_price_per_month":12000,"sort_order":3}'
```

---

## Data model

### SubscriptionPlan

```
id                           UUID (PK)
name                         "Monthly" / "6-Month Package" / "Yearly Package"
slug                         "monthly" / "half-yearly" / "yearly"
description                  optional marketing text
price_per_month              TZS integer (e.g. 25000)
duration_months              int (1 / 6 / 12)
included_stores              int (default 3)
extra_store_price_per_month  TZS integer (default 12000)
is_active                    bool (admin toggles to hide)
sort_order                   int
```

Computed properties:
- `total_price` = `price_per_month × duration_months`
- `extra_store_price_total` = `extra_store_price_per_month × duration_months`

### Subscription

```
id                UUID (PK)
organisation      FK → Organisation
plan              FK → SubscriptionPlan (null for trial)
status            pending_payment | trial | active | expired | cancelled
start_date        date
end_date          date
is_trial          bool
trial_fee         TZS (default 10000)
extra_stores      int (additional paid stores, default 0)
amount_paid       TZS
payment_reference string (M-Pesa code etc.)
payment_date      date (null until payment confirmed)
activated_by      FK → User (admin who confirmed)
notes             text (internal)
```

Computed properties:
- `is_active_now` = `status in (trial, active) AND end_date >= today`
- `days_remaining` = `end_date - today`
- `max_stores_allowed` = `plan.included_stores + extra_stores` (or 3 + extra if no plan)
- `total_amount_due` = trial fee or `plan.total_price + extra_stores_cost`
