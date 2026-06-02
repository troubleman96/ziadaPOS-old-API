# apps/transactions — Sales Transactions & POS Checkout

## What this app does

`apps/transactions` is the core commerce engine of Ziada POS. It owns the data model for every sale ever made in the store, and implements the atomic checkout flow that turns a shopping cart into a committed transaction.

**Two models:**
- `Transaction` — one completed sale (header: totals, payment method, status, cashier)
- `TransactionLine` — individual line items within that sale (one row per product × quantity)

**UI pages this app powers:**
- `/pos` — the "Complete sale →" button triggers `POST /complete-sale/`
- `/transactions` — transaction history list with date grouping, filters, day-level subtotals
- `/transactions/[id]` — transaction detail: line items, payment info, timeline, refund button
- Dashboard **Recent transactions** widget — last 8 transactions
- Dashboard **Today summary** — gross sales, net, profit (from `summary/` endpoint)

---

## Models

### `Transaction`

A single completed sale. One transaction = one customer visit = one receipt.

#### Store context

| Field | Type | Description |
|-------|------|-------------|
| `store` | FK → Store (CASCADE) | Store where this sale took place. All queries scoped by this. |

#### Human-readable ID

| Field | Type | Description |
|-------|------|-------------|
| `txn_number` | CharField(30), unique | Human-readable receipt ID: `TXN-1001`, `TXN-1002`, etc. Sequential per store, generated at checkout time. Not the UUID primary key. |

The UUID `id` is used internally; `txn_number` is shown on receipts, in search, and in audit logs.

#### Payment

| Field | Type | Description |
|-------|------|-------------|
| `payment_method` | CharField(20) | One of: `Cash`, `M-Pesa`, `Tigo Pesa`, `Bank`, `Credit`. |
| `payment_reference` | CharField(100) | Mobile money confirmation code or bank reference. Blank for cash. |

When `payment_method == "Credit"`, the transaction `status` is set to `credit` and a `CreditTab` is automatically created in `apps.credits`.

#### Status lifecycle

| Value | Meaning |
|-------|---------|
| `paid` | Completed, payment received |
| `credit` | On tab — customer owes the amount |
| `refunded` | Previously paid, now reversed |
| `void` | Cancelled before completion |

#### Amounts (TZS integers)

All monetary fields are stored as plain Python integers representing Tanzanian Shillings. No Decimal fields, no currency sub-units.

| Field | Type | Description |
|-------|------|-------------|
| `subtotal` | PositiveIntegerField | Sum of `(line.unit_price × line.qty)` for all lines, before discount. |
| `discount_pct` | DecimalField(5,2) | Discount percentage (e.g. `5.00` for 5%). |
| `discount_amount` | PositiveIntegerField | Absolute discount in TZS: `subtotal × discount_pct / 100`. |
| `tax_amount` | PositiveIntegerField | VAT at 18%: `(subtotal - discount_amount) × 0.18`. |
| `total` | PositiveIntegerField | Net total the customer pays: `subtotal - discount + tax`. |
| `cost_total` | PositiveIntegerField | Sum of `(line.unit_cost × line.qty)` — total COGS. |
| `profit` | IntegerField | `total - cost_total - tax_amount`. Can be negative. |

#### Staff / register

| Field | Type | Description |
|-------|------|-------------|
| `cashier` | FK → User (nullable, SET_NULL) | Staff member who processed the sale. |
| `till_number` | CharField(20) | Register identifier: `"Till #1"`, `"Till #2"`, `"Till #3"`. |

#### Customer

| Field | Type | Description |
|-------|------|-------------|
| `customer_name` | CharField(200) | Display name. Default `"Walk-in"` for anonymous customers. |
| `customer_phone` | CharField(30) | Phone number if known. |
| `customer` | FK → Customer (nullable, SET_NULL) | Link to registered Customer profile. Null for walk-in. |

#### Computed properties

```python
transaction.item_count   # total units sold (sum of all line.qty)
transaction.sku_count    # number of distinct SKUs in this transaction
```

#### DB indexes

- `(store, created_at)` — used for daily summary lookups
- `(status)` — used for credit tab queries and status-filtered lists

---

### `TransactionLine`

One product × quantity within a transaction.

**Critical:** `unit_price` and `unit_cost` are **snapshots taken at the time of sale and are NEVER recalculated.** Product prices change; historical transactions must reflect what was actually charged.

| Field | Type | Description |
|-------|------|-------------|
| `transaction` | FK → Transaction (CASCADE) | Parent transaction. |
| `product` | FK → Product (nullable, SET_NULL) | Inventory product reference. Nullable — a product may be archived later, but the line remains intact via the snapshot fields. |
| `product_name` | CharField(300) | Snapshot of product name at time of sale. |
| `product_sku` | CharField(50) | Snapshot of SKU at time of sale. |
| `unit_price` | PositiveIntegerField | Snapshot of selling price (TZS) at time of sale. |
| `unit_cost` | PositiveIntegerField | Snapshot of unit cost (TZS) at time of sale. |
| `qty` | PositiveIntegerField | Quantity sold. |

#### Computed properties

```python
line.line_total    # unit_price × qty
line.line_cost     # unit_cost × qty
line.line_profit   # line_total - line_cost
```

---

## API Endpoints

All routes mount at `/api/v1/transactions/`.

### `POST /complete-sale/`

**The core POS action.** Processes a shopping cart into a committed transaction. The entire flow runs inside `@db_transaction.atomic`.

**Auth:** `IsAuthenticated`, `IsStoreCashier`

**Request body:**
```json
{
  "items": [
    { "product_id": "uuid", "qty": 2 },
    { "product_id": "uuid", "qty": 1 }
  ],
  "payment_method": "M-Pesa",
  "payment_reference": "QGT5K3AB",
  "discount_pct": "5.00",
  "till_number": "Till #1",
  "customer_id": "uuid-or-null",
  "notes": ""
}
```

**Processing steps (all atomic — any failure rolls back everything):**
1. Validate all `product_id` values exist in the user's store and are active
2. Calculate `subtotal`, `discount_amount`, `tax_amount`, `total`, `cost_total`, `profit`
3. Resolve optional `customer_id` → Customer object (falls back to walk-in if not found)
4. Generate next sequential `txn_number` using string-max over existing `TXN-*` values
5. Create `Transaction` record
6. Create `TransactionLine` for each cart item
7. Deduct stock: `product.stock -= qty` for each item
8. Create `StockAdjustment(type="sale")` for each item
9. If `payment_method == "Credit"` and customer linked: create `CreditTab` in `apps.credits`

**Returns:** 201 with full `TransactionSerializer` response including all lines.

---

### `GET /`

Paginated list of transactions for the user's store, newest first.

**Query params:**

| Param | Effect |
|-------|--------|
| `?status=paid\|credit\|refunded\|void` | Filter by status |
| `?method=M-Pesa\|Cash\|…` | Filter by payment method |
| `?search=TXN-2043` | Search txn_number, customer_name, customer_phone, payment_reference |
| `?date_from=YYYY-MM-DD` | From date (inclusive) |
| `?date_to=YYYY-MM-DD` | To date (inclusive) |
| `?ordering=-total` | Sort by created_at, total, or status |

Uses `TransactionListSerializer` (no nested lines) for performance.

---

### `GET /{id}/`

Full transaction detail including all `lines` (uses `TransactionSerializer`).

---

### `POST /{id}/refund/`

**Auth:** `IsAuthenticated`, `IsStoreCashier`

Refunds a `paid` transaction. Sets `status = "refunded"`, restores stock for each line, creates `StockAdjustment(type="refund")` records.

```json
{ "reason": "Customer returned — wrong product" }
```

Error 400 if `status != "paid"`.

---

### `GET /summary/`

Aggregate KPI stats. Supports the same date filters as the list endpoint.

**Response:**
```json
{
  "total_inflow": 4850000,
  "total_profit": 820000,
  "total_cost": 3200000,
  "transaction_count": 87,
  "on_credit": 350000,
  "credit_count": 3,
  "refunds": 45000,
  "refund_count": 1,
  "margin_pct": 16.9
}
```

---

## TXN Number Generation

`_generate_txn_number(store)` finds the last `TXN-NNNN` for this store:

```python
last = Transaction.objects.filter(store=store, txn_number__startswith="TXN-").order_by("-txn_number").first()
```

Runs inside the atomic block, so concurrent checkouts don't duplicate numbers. New stores start at `TXN-1001` (4 digits).

---

## Signals & Analytics Integration

`apps/analytics/signals.py` listens for `Transaction` post-save events and rebuilds the `DailySummary` row for today. Wired in `AnalyticsConfig.ready()`:

```python
from apps.transactions.models import Transaction
post_save.connect(update_daily_summary, sender=Transaction)
```

---

## Design Decisions

**Why `@db_transaction.atomic` for the entire checkout?**
A POS sale touches multiple tables: `Transaction`, N `TransactionLine` rows, N `Product` stock updates, N `StockAdjustment` rows, and optionally a `CreditTab`. A partial save corrupts inventory and creates phantom revenue. The atomic block ensures everything succeeds or nothing does.

**Why store `cost_total` and `profit` on `Transaction`?**
These could be recomputed from `TransactionLine` records but would require N+1 queries for list views. Storing them as denormalized integers makes the `/transactions` list fast.

**Why `discount_pct` as `DecimalField` but amounts as integers?**
The percentage input (e.g. `12.5%`) needs decimal precision. The computed `discount_amount` is then rounded to the nearest TZS integer. Using `Decimal` for the input prevents floating-point rounding errors during the intermediate calculation.

**Why price snapshots on `TransactionLine`?**
If we stored only the product FK, a price change would silently alter historical profit figures. Snapshots make historical profit immutable and accurate regardless of what happens to the product afterwards.

---

## Common Gotchas

1. **`complete-sale/` must be declared BEFORE the router** in `urls.py`. The `DefaultRouter` would otherwise match `complete-sale/` as a detail lookup for `pk="complete-sale"`.

2. **`txn_number` ordering uses string comparison.** This works correctly while all numbers have 4+ digits (TXN-1001 to TXN-9999). If a store exceeds TXN-9999, ordering breaks until zero-padded or switched to integer extraction.

3. **Refunding a `credit` transaction is blocked.** Status must be `"paid"`. Credit transactions are managed via `apps.credits` — they don't go through the refund endpoint.

4. **`profit` is `IntegerField`, not `PositiveIntegerField`.** Negative profit is valid (discounted below cost, or damaged goods).

5. **`customer.total_spent` and `customer.last_visit` are not updated here.** These cached fields on `Customer` need to be refreshed when a transaction is completed. Check `apps/customers` for the signal or management command that handles this.
