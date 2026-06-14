# ZiadaPos Production Remediation Plan

## Goals (P0 — fix this week)

1. **TXN race condition** — prevent duplicate `txn_number` under parallel tills.
2. **Credit-limit enforcement** — block credit sales that exceed the customer's allowed ceiling.
3. **Stock-underflow guard** — prevent negative stock and add a safety check.

---

## 1. TXN race condition

### Problem
`_generate_txn_number()` does `MAX(txn_number)+1` inside the sales atomic block,
but two tills can read the same max before either writes, causing `IntegrityError`
on the unique `Transaction.txn_number` and a 500 to the cashier.

### Approach
Introduce a lightweight `TxnSequence` table keyed by `store`. Each sale uses
`select_for_update()` on the row and increments a counter — atomic, single-row
lock, no deadlocks.

### Files to touch

| File | Change |
|------|--------|
| `apps/transactions/models.py` | Add `TxnSequence` model (`store` FK, `last_number`, unique together) |
| `apps/transactions/api/views.py` | Replace `_generate_txn_number()` body with a `select_for_update().get_or_create()` + increment pattern |

### Rollback / risk
Low risk. Old code path can be kept and commented out; the sequence model is additive.
On deployment, existing `TXN-NNNN` numbers continue to work (we parse the numeric
part and seed `last_number` from the current max on first use).

---

## 2. Credit-limit enforcement

### Problem
`Customer.credit_limit` is stored but never checked in `CompleteSaleView`.
Any cashier can issue an unlimited tab.

### Approach
Add a single check in `_process_sale()` before creating the `CreditTab`:
if `customer.credit_limit is not None` and `customer.open_credit + total > customer.credit_limit`
→ return a clear 400 so the UI can surface it.

### Files to touch

| File | Change |
|------|--------|
| `apps/transactions/api/views.py` | In `_process_sale()`, after customer resolution and before creating the `Transaction`, add the limit check. |

### Rollout note
Existing customers with `credit_limit=None` are unaffected (no limit).
Setting the field on a customer now becomes meaningful.

---

## 3. Stock-underflow guard

### Problem
`product.stock -= line["qty"]` never checks whether stock is sufficient.
Typos or race conditions leave `stock < 0`, which the POS UI then shows as
"sellable".

### Approach
Option A (safe default): refuse sale when `stock < qty` for at least one line —
return a 400 with the offending product(s). Option B (lenient): allow negative
but log a `WARNING` so ops can catch it.

Recommendation: **Option A** for a POS — you don't want to sell what you don't have.

### Files to touch

| File | Change |
|------|--------|
| `apps/transactions/api/views.py` | Before deducting stock, verify `product.stock >= qty` for every line. If any fail, return `error_response("Insufficient stock for: ...", status=400)` |

---

## Implementation order

```
Phase 1 — models.py   : add TxnSequence (no behavior change yet)
Phase 2 — views.py    : 
   a) stock guard      (fast, visible to cashiers immediately)
   b) credit limit     (fast, closes the madeni risk today)
   c) txn sequence     (last; depends on TxnSequence being migrated)
Phase 3 — migrations  : create and apply
Phase 4 — test        : register a quick smoke test via curl
```

---

## Testing (manual)

```bash
# 1) Register a fresh owner
curl -s -X POST http://127.0.0.1:8096/api/v1/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"full_name":"Test User","phone":"0799999999","password":"StrongPass1!","confirm_password":"StrongPass1!","main_shop_name":"Test Shop","business_type":"retail","region":"Dar es Salaam"}' | python3 -m json.tool

# 2) Login to get tokens (extract access)
curl -s -X POST http://127.0.0.1:8096/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"phone":"0799999999","password":"StrongPass1!"}' | python3 -m json.tool

# 3) Create a product with stock=5
#    Use the access token from step 2 in Authorization: Bearer <token>

# 4) Attempt a credit sale exceeding credit_limit
#    → expect 400 {"errors": {"credit": ["...exceeds limit..."]}}

# 5) Attempt a sale qty=10 on the product above
#    → expect 400 with "Insufficient stock"

# 6) Fire two parallel complete-sale requests on two tills
#    → both should return 201 with distinct TXN numbers (no 500)
```
