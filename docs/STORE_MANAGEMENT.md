# Store Management

## Overview

Every `Organisation` can have multiple `Store` records (branches). The number of stores is controlled by the organisation's **subscription** — specifically `organisation.max_stores`.

---

## Store limits per subscription

| Subscription | Stores included | Extra stores |
|--------------|-----------------|--------------|
| Trial (all packages) | 3 | 12,000 TZS/month each |
| Monthly (25,000 TZS/month) | 3 | 12,000 TZS/month each |
| 6-Month (23,000 TZS/month) | 3 | 12,000 TZS/month each |
| Yearly (22,000 TZS/month) | 3 | 12,000 TZS/month each |

Extra stores are charged separately and granted by Cameltech admins after payment confirmation. The `max_stores` value on the `Organisation` model is the single source of truth for the limit.

---

## Check if a store can be added

**Endpoint:** `GET /api/v1/subscriptions/store-limit/`  
**Auth required:** Owner or admin

The UI should call this before showing the "Add Store" form to gate access correctly.

### Response

```json
{
  "success": true,
  "data": {
    "can_add_store":               true,
    "current_active_stores":       2,
    "max_stores_allowed":          3,
    "remaining_slots":             1,
    "extra_store_price_per_month": 12000,
    "subscription_status":         "trial",
    "subscription_is_active":      true,
    "days_remaining":              5,
    "message": "You can add 1 more store."
  }
}
```

### When at limit

```json
{
  "success": true,
  "data": {
    "can_add_store":               false,
    "current_active_stores":       3,
    "max_stores_allowed":          3,
    "remaining_slots":             0,
    "extra_store_price_per_month": 12000,
    "subscription_status":         "active",
    "subscription_is_active":      true,
    "days_remaining":              18,
    "message": "You have reached your 3-store limit. Additional stores cost 12,000 TZS/month. Contact Ziada support to purchase more store slots."
  }
}
```

### UI gating logic

```
if can_add_store == true
  → Enable "Add Store" button
  → Show "X slots remaining" badge

if can_add_store == false
  → Disable "Add Store" button
  → Show "Store limit reached. Contact us to add more — 12,000 TZS/month."
  → Show contact button/link
```

---

## Create a store

**Endpoint:** `POST /api/v1/stores/`  
**Auth required:** Owner or admin

```json
{
  "name":       "Mwenge Branch",
  "area":       "Mwenge",
  "address":    "Mwenge Street, Dar es Salaam",
  "phone":      "0752000001",
  "code":       "MWG",
  "till_count": 2,
  "open_hours": "8:00 AM – 8:00 PM"
}
```

- The `organisation` is automatically inferred from the authenticated owner — **do not pass it in the request**.
- New stores are always created as `is_active=True`.
- Store names must be unique within an organisation.

### Success (201 Created)

```json
{
  "success": true,
  "message": "Store 'Mwenge Branch' created.",
  "data": { ...StoreListSerializer... }
}
```

### At limit (403 Forbidden)

```json
{
  "success": false,
  "message": "Store limit reached (3/3). Additional stores cost 12,000 TZS/month. Contact Ziada support to purchase more store slots.",
  "errors": {
    "can_add_store":               false,
    "current_active_stores":       3,
    "max_stores_allowed":          3,
    "extra_store_price_per_month": 12000,
    "action":                      "contact_support"
  }
}
```

The `action: "contact_support"` field tells the UI what button to show (e.g., WhatsApp link, contact form).

---

## Update a store

**Endpoint:** `PATCH /api/v1/stores/{id}/`  
**Auth required:** Owner (own org) or admin

Pass only the fields to update. All fields are optional.

---

## Deactivate (soft-delete) a store

**Endpoint:** `DELETE /api/v1/stores/{id}/`  
**Auth required:** Owner (own org) or admin

Sets `is_active=False` and `status=paused`. The store disappears from the store switcher but data is preserved. Deactivated stores do NOT count against the limit.

---

## Grant extra store slots (admin only)

When an owner pays for additional stores (outside the app), the Cameltech admin grants access:

**Option A — Django Admin panel:**
1. Go to `/admin/`
2. Navigate to **Subscriptions → Subscriptions**
3. Find the organisation's subscription
4. Set `extra_stores` to the number of additional paid stores
5. Save → `organisation.max_stores` is automatically updated

**Option B — API:**

`PATCH /api/v1/subscriptions/all/{subscription_id}/extra-stores/`

```json
{ "extra_stores": 1 }
```

Response confirms the new `max_stores_allowed`:

```json
{
  "success": true,
  "message": "Extra store slots updated to 1. Organisation can now have up to 4 stores.",
  "data": {
    "org_max_stores_now": 4,
    ...
  }
}
```

After this, the owner can immediately add the new store via `POST /api/v1/stores/`.

---

## How max_stores stays in sync

`organisation.max_stores` is updated automatically whenever:
1. **Subscription activated** → set to `plan.included_stores + subscription.extra_stores`
2. **Extra stores granted** → recalculated and saved to org
3. **Registration** → defaults to 3 (base package for all plans)

The calculation: `max_stores = plan.included_stores + extra_stores`

For the trial (no plan selected yet): base = 3 + extra_stores.

---

## Store model fields

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Unique within the org |
| `area` | string | Neighbourhood shown in sidenav (e.g. "Kariakoo") |
| `code` | string | Short code for transaction IDs (e.g. "KRC" → TXN-KRC-2043) |
| `address` | text | Full physical address |
| `phone` | string | Store contact phone |
| `till_count` | int | Number of POS registers |
| `open_hours` | string | Display label (e.g. "7:00 AM – 9:00 PM") |
| `is_main_store` | bool | True for the first store created at registration |
| `is_active` | bool | False = soft-deleted |
| `status` | choice | `open`, `closed`, `paused` |
| `color` | hex | UI avatar colour |
