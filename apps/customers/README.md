# apps/customers — Customer Profiles & Segments

## What this app does

`apps/customers` manages the store's registered customer directory. It stores identity, contact, loyalty segment, and cached spend statistics for every named customer — the ones who show up by name rather than as "Walk-in".

Walk-in customers do **not** exist here. They live only as `customer_name = "Walk-in"` on `Transaction`. The `Customer` model is for recurring, registered buyers.

**UI pages this app powers:**
- `/customers` — customer list: searchable, segmented (VIP/Regular/Occasional/New), sortable by spend/last visit/ticket, KPI strip at the top
- `/customers/[id]` — customer detail: full profile, stats, transaction history
- `/customers/new` — add customer form
- `/credits` — references `Customer` via `CreditTab` and `customer.open_credit`
- `/pos` — the customer selector (credit sales require a registered customer)

---

## Model: `Customer`

A registered customer of a store. Scoped to one store — customers are not shared across stores.

### Core fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key (BaseModel) |
| `store` | FK → Store (CASCADE) | Store this customer belongs to. |
| `name` | CharField(200) | Full name, e.g. "Fatuma Ally". |
| `phone` | CharField(30) | International format, e.g. "+255 712 345 678". Used for WhatsApp reminders and search. |
| `email` | EmailField | Optional. For future email receipts. |

**`unique_together = [("store", "phone")]`** — same phone can appear in different stores, but not twice in the same store. A customer with no phone can be created (phone is blank-allowed), but only one blank-phone customer per store is not enforced.

### Segmentation

| Field | Type | Description |
|-------|------|-------------|
| `segment` | CharField(20) | `VIP`, `Regular`, `Occasional`, or `New`. Default `New`. |

Segment is stored, not computed on-the-fly. This allows staff to manually override it. Suggested thresholds (not enforced by code):
- `VIP` → lifetime spend > 1,000,000 TZS
- `Regular` → lifetime spend > 200,000 TZS and recency < 60 days
- `Occasional` → recurring but infrequent
- `New` → created within last 60 days or first purchase

A nightly management command or signal can auto-update segments based on `total_spent` and `last_visit`.

### Denormalized cache fields

These fields are updated every time a transaction is completed or refunded. They exist to avoid expensive aggregation queries on the customer list view.

| Field | Type | Description |
|-------|------|-------------|
| `total_spent` | PositiveIntegerField | Lifetime total spend (TZS). Drives the default ordering (VIPs first). |
| `last_visit` | DateField (nullable) | Date of last completed paid transaction. |
| `avg_ticket` | PositiveIntegerField | Average transaction total (TZS). |
| `open_credit` | PositiveIntegerField | Current outstanding credit balance (TZS). Updated by `apps.credits` when tabs are created or payments are recorded. |

### Display

| Field | Type | Description |
|-------|------|-------------|
| `avatar_hue` | PositiveSmallIntegerField | 0–360 colour hue for the avatar gradient. Set randomly on creation. No image stored — frontend renders a CSS gradient. Default 200 (blue). |
| `notes` | TextField | Internal notes visible on the customer card. |
| `is_active` | BooleanField | Soft-delete flag. Inactive customers are hidden from lists but not deleted. Historical transactions and credit tabs are unaffected. |

### Computed properties

```python
customer.initials       # str: "FA" from "Fatuma Ally" (first two words, first letters, uppercase)
customer.has_open_credit  # bool: open_credit > 0
```

### Meta

- **Ordering:** `["-total_spent"]` — VIP customers appear first in all list queries.
- **DB indexes:** `(store, is_active)`, `(segment)`

---

## API Endpoints

All routes mount at `/api/v1/customers/` via `DefaultRouter`.

### `GET /`

**View:** `CustomerViewSet.list`
**Auth:** `IsAuthenticated`

Paginated customer list for the user's store. Defaults to active customers only, sorted by total_spent descending.

**Query params:**

| Param | Example | Effect |
|-------|---------|--------|
| `?segment=VIP` | `?segment=VIP` | Filter by segment. `?segment=All` or omit for all segments. |
| `?has_credit=true` | `?has_credit=true` | Only customers with `open_credit > 0`. Used by `/credits` page. |
| `?is_active=false` | `?is_active=false` | Show only archived/inactive customers. |
| `?search=Fatuma` | `?search=Fatuma` | Search across `name`, `phone`, `email`. |
| `?ordering=-total_spent` | `?ordering=-total_spent` | Sort by `total_spent`, `last_visit`, `avg_ticket`, `open_credit`, `created_at`. |

Uses `CustomerListSerializer` for efficiency (subset of fields, no nested data).

---

### `POST /`

**View:** `CustomerViewSet.create`
**Auth:** `IsAuthenticated`, `IsStoreManager` (checked inline)

Creates a new customer. Store is injected server-side from `request.user.store`.

**Request body:**
```json
{
  "name": "Fatuma Ally",
  "phone": "+255712345678",
  "email": "fatuma@example.com",
  "segment": "Regular",
  "notes": "Prefers credit payments"
}
```

Returns 201 with full `CustomerSerializer` response.

**Errors:**
- 403 if user role is `cashier` (only manager/owner/admin can add customers)
- 400 if phone already exists in this store

---

### `GET /{id}/`

Full customer profile with all stats. Uses `CustomerSerializer`.

---

### `PATCH /{id}/`

**Auth:** `IsAuthenticated`, `IsStoreManager` (checked inline)

Partial update. `CustomerUpdateSerializer` allows: `name`, `phone`, `email`, `segment`, `notes`.

---

### `DELETE /{id}/`

**Auth:** `IsAuthenticated`, `IsStoreManager` (checked inline)

Soft-delete: sets `is_active=False`. All transactions, credit tabs, and payments referencing this customer are preserved. Returns 204 No Content.

---

### `GET /summary/`

**View:** `CustomerViewSet.summary` (extra action)
**Auth:** `IsAuthenticated`

Aggregate KPI stats for the `/customers` page header strip.

**Response:**
```json
{
  "total_customers": 142,
  "total_lifetime_value": 18500000,
  "total_open_credit": 850000,
  "avg_ticket": 32000,
  "active_this_month": 67,
  "on_credit_count": 12,
  "by_segment": {
    "VIP": 8,
    "Regular": 45,
    "Occasional": 61,
    "New": 28
  }
}
```

`active_this_month` = customers with `last_visit >= today - 30 days`.

---

## Serializers

Three serializers are used for different contexts:

| Serializer | Used for | Fields |
|------------|---------|--------|
| `CustomerListSerializer` | List views | id, name, phone, segment, total_spent, last_visit, avg_ticket, open_credit, avatar_hue, initials |
| `CustomerSerializer` | Detail, create response | All fields including notes, email, is_active, created_at |
| `CustomerCreateSerializer` | POST /customers/ | name, phone, email, segment, notes — validates phone uniqueness in context store |
| `CustomerUpdateSerializer` | PATCH /customers/{id}/ | name, phone, email, segment, notes — partial update safe |

---

## Relationship to Credits App

`apps.credits` is the primary updater of `customer.open_credit`. Every time a `CreditPayment` is recorded or a `CreditTab` is written off, `_refresh_customer_credit(customer)` recalculates the balance and saves it to `customer.open_credit`. This coupling is intentional — the customer object is the single source of truth for "does this customer owe us money?"

The credits app also uses `Customer.objects.filter(store=store, open_credit__gt=0)` to build the credits dashboard, which relies on this cached field being accurate.

---

## Design Decisions

**Why are cache fields denormalized on `Customer`?**
The `/customers` list view needs to sort and display spend stats for potentially hundreds of customers. Computing `SUM(transaction.total)` grouped by customer on every page load would be an expensive multi-table join. The denormalized `total_spent`, `last_visit`, and `avg_ticket` fields make this a simple `ORDER BY total_spent` query.

**Why is `segment` stored and not computed?**
Segments are fuzzy and store-specific. One store might define VIP as "spent > 500k", another as "spent > 2M". Storing the segment allows manual override by the manager ("this customer is loyal but hasn't spent much — mark them Regular"). An automated job can suggest segment updates but the manager has final say.

**Why `PROTECT` on the FK from `CreditTab` to `Customer`?**
See `apps/credits` — CreditTab uses `PROTECT` to prevent customer deletion when open debts exist. This means you can't `DELETE /customers/{id}/` via the API if the customer has open credit tabs — the API soft-deletes (is_active=False) so this is fine, but a direct ORM `customer.delete()` would raise an error.

**Why `unique_together = [("store", "phone")]` instead of global phone uniqueness?**
The same person might register at two different stores in the same organisation (e.g. two branches of the same chain). Global phone uniqueness would block this. Store-scoped uniqueness is the right boundary.

---

## Common Gotchas

1. **`customer.open_credit` is a cached field.** It's only as current as the last `_refresh_customer_credit()` call. If you manipulate `CreditTab` or `CreditPayment` outside the standard views, always call `_refresh_customer_credit(customer)` afterwards.

2. **`customer.total_spent` and `customer.last_visit` are NOT automatically updated by `apps.transactions`.** These need to be updated in a signal or after a successful transaction. Check `apps/customers/signals.py` or the analytics rebuild process.

3. **`avatar_hue` is set to 200 by default.** If you bulk-import customers without randomizing this, all imported customers will have the same blue avatar. Set it to `random.randint(0, 360)` during import.

4. **Inactive customers (`is_active=False`) still appear in credit tabs.** `CreditsDashboardView` filters on `is_active=True`, so archived customers are hidden from the credits dashboard even if they still have open tabs. This means write-offs on archived customers' tabs should be done before archiving.

5. **The `has_credit=true` filter** is a shortcut for `?open_credit__gt=0`. It returns the same results as filtering `customer.open_credit > 0` but is semantically clearer for callers that just want "customers with outstanding debt."
