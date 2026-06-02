# apps/credits — Customer Credit ("Madeni") Management

## What this app does

`apps/credits` implements the credit ledger for Ziada POS — the system that tracks when customers buy on tab ("madeni" in Swahili), records their payments, and manages follow-up communications. It is the backend for the `/credits` section of the UI.

The credit lifecycle:
1. Cashier selects "Credit" as payment method at POS
2. `CompleteSaleView._process_sale()` creates a `Transaction(status="credit")` AND a `CreditTab`
3. The tab appears in `/credits` under the customer's name
4. When the customer pays, staff records a `CreditPayment`
5. The payment is automatically distributed across open tabs (oldest first)
6. When a tab is fully paid, its status changes to `settled`
7. Staff can log WhatsApp messages, phone calls, or SMS reminders as `CreditMessage` records
8. Staff can add internal-only notes as `CreditNote` records
9. Managers can write off irrecoverable tabs

**UI pages this app powers:**
- `/credits` — KPI strip (total outstanding, overdue, due soon, recovered this month), aging buckets, customer list sorted by urgency
- `/credits/[id]` — full customer credit profile: open tabs, payment history, message log, internal notes

---

## Models

### `CreditTab`

One credit sale tab. Created automatically by `CompleteSaleView` when `payment_method == "Credit"`. Each tab represents one transaction done on credit.

**Status values:**

| Value | Meaning |
|-------|---------|
| `open` | No payments have been made |
| `partially_paid` | Some payments have been applied, balance remains |
| `settled` | Fully paid |
| `written_off` | Irrecoverable — manager decision |

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `customer` | FK → Customer (PROTECT) | Customer who owes this debt. PROTECT prevents accidental customer deletion when tabs exist. |
| `transaction` | OneToOneField → Transaction (nullable, SET_NULL) | The POS transaction that created this tab. Nullable to allow manually-created tabs. |
| `store` | FK → Store (CASCADE) | Denormalized from `customer.store` for fast store-scoped queries. |
| `amount` | PositiveIntegerField | Total amount of the credit sale (TZS). |
| `amount_paid` | PositiveIntegerField | Cached sum of payments applied to this tab (TZS). Default 0. |
| `status` | CharField(20) | `open` / `partially_paid` / `settled` / `written_off` |
| `due_date` | DateField (nullable) | Payment deadline. Default: 30 days after creation (set by caller). |
| `write_off_reason` | TextField | Reason for write-off, if applicable. |
| `cashier` | FK → User (nullable, SET_NULL) | Staff member who issued the credit. |
| `till_number` | CharField(20) | Register where credit was issued. |

**DB indexes:** `(customer, status)`, `(store, status)`, `(due_date)` — all used by the dashboard aging and customer list queries.

**Computed properties:**

```python
tab.balance      # int: amount - amount_paid (minimum 0)
tab.is_overdue   # bool: due_date < today and status in (open, partially_paid)
tab.txn_number   # str: linked transaction number or "—"
```

---

### `CreditPayment`

A payment made by a customer towards their outstanding credit balance.

Payments are **linked to the Customer, not to a specific tab.** This is intentional: real-world customers often hand over a lump sum ("here's TZS 50,000") without specifying which tab to apply it to. The system distributes payments across tabs oldest-first automatically.

**Payment methods:** `Cash`, `M-Pesa`, `Bank`, `Tigo Pesa`

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `customer` | FK → Customer (PROTECT) | Customer making this payment. |
| `store` | FK → Store (CASCADE) | Store where payment was recorded. |
| `amount` | PositiveIntegerField | Payment amount (TZS). |
| `method` | CharField(20) | Payment channel. |
| `reference` | CharField(100) | M-Pesa code, bank reference, etc. |
| `cashier` | FK → User (nullable, SET_NULL) | Staff member who recorded this payment. |
| `note` | TextField | Optional note (e.g. "Partial payment, rest next week"). |

---

### `CreditMessage`

A communication record for credit follow-up. Stores outbound reminders, inbound replies, phone call logs, and SMS notifications. Shown as a timeline in `/credits/[id]`.

**Kinds:** `whatsapp`, `call`, `sms`
**Directions:** `in` (from customer), `out` (to customer)

| Field | Type | Description |
|-------|------|-------------|
| `customer` | FK → Customer (CASCADE) | Customer involved. |
| `store` | FK → Store (CASCADE) | Store context. |
| `kind` | CharField(20) | `whatsapp` / `call` / `sms` |
| `direction` | CharField(5) | `in` / `out` |
| `body` | TextField | Message text or call summary. |
| `who` | CharField(100) | Sender display name: e.g. `"Hamisi M."` or `"auto-reminder"`. |
| `sent_by` | FK → User (nullable, SET_NULL) | Staff user (null for automated messages). |

**Note:** The MVP logs the message but does not actually send it. The frontend uses the stored message body to open a WhatsApp deep link. Actual WhatsApp Business API integration is future scope.

---

### `CreditNote`

Internal staff note on a customer's credit relationship. **Not visible to the customer.** Appears in `/credits/[id]` as a private note thread.

Use cases: `"Agreed to pay end of month"`, `"Do not extend credit — payment history is unreliable"`.

| Field | Type | Description |
|-------|------|-------------|
| `customer` | FK → Customer (CASCADE) | Customer this note is about. |
| `store` | FK → Store (CASCADE) | Store context. |
| `body` | TextField | Note content. |
| `by` | FK → User (nullable, SET_NULL) | Staff member who wrote this note. |

---

## API Endpoints

All routes mount at `/api/v1/credits/`.

### `GET /`

**View:** `CreditsDashboardView`
**Auth:** `IsAuthenticated`

Powers the entire `/credits` page in one call. Returns:
- **KPI strip:** `total_outstanding`, `overdue`, `due_soon`, `recovered_month`, `customer_count`
- **Aging buckets:** 5 buckets by days overdue (see below)
- **Customer list:** each customer's balance, credit status, due_days, last tab date, last payment

**Query params:**
- `?status=overdue|due-soon|current` — filter the customer list
- `?search=Fatuma` — search by name or phone

**Aging buckets** (based on days past due date):
```
Current (0 days)  — not yet due
1–7 days          — 1 to 7 days overdue
8–30 days         — 8 to 30 days overdue
31–60 days        — 31 to 60 days overdue
60+ days          — more than 60 days overdue
```

**Customer status logic** (computed per customer):
- `overdue` — any open tab has `due_date < today`
- `due-soon` — nearest due date is within 7 days
- `current` — all tabs are not yet due

Customers are sorted by `due_days` ascending — most overdue first.

---

### `GET /customers/{customer_id}/`

**View:** `CustomerCreditProfileView`
**Auth:** `IsAuthenticated`

Full credit profile for a specific customer. Returns:
```json
{
  "customer": { "id", "name", "phone", "open_credit", "segment", ... },
  "tabs": [...],
  "payments": [...],
  "messages": [...],
  "notes": [...],
  "total_owed": 250000,
  "total_paid": 100000,
  "open_balance": 150000,
  "tab_count": 3,
  "payment_count": 2
}
```

---

### `POST /customers/{customer_id}/record-payment/`

**View:** `RecordPaymentView`
**Auth:** `IsAuthenticated`, `IsStoreCashier`

Records a payment and automatically distributes it across open tabs (oldest first).

**Request body:**
```json
{
  "amount": 50000,
  "method": "M-Pesa",
  "reference": "QGT5K3AB",
  "note": "Customer paid via M-Pesa"
}
```

**Processing (inside `@db_transaction.atomic`):**
1. Create `CreditPayment` record
2. `_apply_payment_to_tabs(customer, amount)` — distributes amount across open/partial tabs oldest-first
3. Each affected tab: `amount_paid += applied`, status updated to `partially_paid` or `settled`
4. `_refresh_customer_credit(customer)` — recalculates and saves `customer.open_credit`

Returns the created `CreditPayment` and the updated `open_credit` balance.

Error 400 if customer has no outstanding balance.

---

### `POST /customers/{customer_id}/send-reminder/`

**View:** `SendReminderView`
**Auth:** `IsAuthenticated`, `IsStoreCashier`

Logs a communication event (WhatsApp, call, SMS) in the credit message thread.

```json
{
  "kind": "whatsapp",
  "direction": "out",
  "body": "Habari Fatuma, tafadhali kumbuka kulipa TZS 150,000 unayodaiwa.",
  "who": "Hamisi M."
}
```

Returns the created `CreditMessage` record. The `who` field defaults to the authenticated user's full name if not provided.

---

### `POST /customers/{customer_id}/add-note/`

**View:** `AddCreditNoteView`
**Auth:** `IsAuthenticated`, `IsStoreCashier`

Adds an internal staff note (not customer-visible).

```json
{ "body": "Customer promised to pay on June 1st" }
```

---

### `POST /tabs/{tab_id}/write-off/`

**View:** `WriteOffTabView`
**Auth:** `IsAuthenticated`, `IsStoreManager`

Writes off a credit tab — marks it `written_off` and removes its balance from `customer.open_credit`.

```json
{ "reason": "Customer relocated — uncontactable" }
```

Error 400 if tab is already `settled` or `written_off`.

---

## Payment Distribution Algorithm

`_apply_payment_to_tabs(customer, amount_to_apply)`:

```python
open_tabs = CreditTab.objects.filter(
    customer=customer,
    status__in=["open", "partially_paid"],
).order_by("created_at")  # oldest first

remaining = amount_to_apply
for tab in open_tabs:
    if remaining <= 0:
        break
    apply = min(remaining, tab.balance)
    tab.amount_paid += apply
    remaining -= apply
    tab.status = "settled" if tab.amount_paid >= tab.amount else "partially_paid"
    tab.save(update_fields=["amount_paid", "status", "updated_at"])
```

This is always followed by `_refresh_customer_credit(customer)` which recalculates `customer.open_credit` from the DB.

---

## Design Decisions

**Why link `CreditPayment` to `Customer` not to a specific `CreditTab`?**
In practice, customers hand over a lump sum without saying which tab it covers. Staff want to record "Fatuma paid TZS 80,000" without having to mentally allocate it across her three tabs. The oldest-first distribution matches common credit management practice (FIFO — oldest debts cleared first).

**Why `PROTECT` on the customer FK?**
A `CreditTab` represents real financial exposure. Deleting a customer who has open tabs would lose the debt record. `PROTECT` forces an explicit decision: settle or write off all tabs before the customer can be removed from the system.

**Why `amount_paid` cached on `CreditTab` instead of summing payments?**
`CreditPayment` is linked to the customer, not the tab. There's no direct FK from `CreditPayment` to `CreditTab`. Rather than finding which portion of each payment was applied to each tab (which would require a junction table), we maintain `amount_paid` as a running total updated atomically during `_apply_payment_to_tabs`.

**Why store `store` denormalized on `CreditTab`, `CreditPayment`, and `CreditMessage`?**
`customer.store` provides the same information, but store-scoped queries on credit models (e.g. "all open tabs for this store") would otherwise require a JOIN through `customer`. The denormalized `store` FK enables direct filtering without the join.

---

## Common Gotchas

1. **`CreditTab.is_overdue` does a DB query** — it calls `timezone.now().date()` each time. Don't call it in a loop over many tabs; instead compute today once and compare `tab.due_date < today` directly.

2. **`_refresh_customer_credit` must be called after every tab status change.** If you modify tabs outside the standard views (e.g. in a management command), always call this function to keep `customer.open_credit` in sync. Stale `open_credit` values cause the credits dashboard to show wrong totals.

3. **`CreditTab.amount_paid` is a cached value, not the sum of payments.** A `CreditPayment` is linked to the customer — the allocation to specific tabs is tracked only via the `amount_paid` field on each tab. If you need to know which specific payments covered a specific tab, that audit trail does not currently exist.

4. **Write-off does not create a `CreditPayment` record.** A written-off tab's balance disappears from `customer.open_credit` but there is no payment record. If you need a full balance-sheet reconciliation, write-offs need to be tracked as a separate accounting entry.

5. **The "send-reminder" endpoint stores messages but does NOT send them.** The frontend opens a WhatsApp deep link using the stored `body`. Actual WhatsApp Business API integration is a future feature.
