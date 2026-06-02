# apps/core — Shared Foundation

`apps/core` is not a feature app — it has no endpoints and no business logic.
It is the **infrastructure layer** that every other Ziada app builds on.
Touch this layer rarely; when you do, the effect is system-wide.

---

## What lives here

| File | Purpose |
|------|---------|
| `models.py` | `BaseModel` — abstract base every model inherits |
| `response.py` | `success_response` / `error_response` — standard JSON envelope |
| `pagination.py` | `StandardResultsPagination` — uniform page format for all list views |
| `exceptions.py` | `custom_exception_handler` — converts DRF exceptions to standard shape |
| `permissions.py` | `IsOrganisationAdmin`, `IsStoreManager`, `IsStoreCashier`, `IsReadOnly` |

---

## models.py — BaseModel

Every model in Ziada inherits from `BaseModel`. It adds three columns to every
table automatically.

### Fields

```python
id         = UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
created_at = DateTimeField(auto_now_add=True)
updated_at = DateTimeField(auto_now=True)
```

**`id` — UUID4 primary key**
Django's default is an auto-incrementing integer. We override this because:
- Integers are guessable. If a transaction has id `1042`, the next is probably `1043`.
  An attacker can crawl records by incrementing. UUIDs are random 128-bit values —
  there is no useful next value to guess.
- Safe to expose in public URLs (`/transactions/550e8400-e29b-...`) without leaking
  record count or insertion order.
- Safe for multi-tenant use — two organisations' records will never share an id,
  even if created at the same millisecond on different servers.

`uuid.uuid4` is passed as a **callable** (not `uuid.uuid4()`), so each new instance
gets its own UUID at construction time rather than sharing one at import time.

**`created_at` — set once on first INSERT**
`auto_now_add=True` writes `now()` exactly once. The field is immutable after that.
Use it for "when did this happen?" queries and sorting.

**`updated_at` — refreshed on every save()**
`auto_now=True` calls `datetime.now()` and overwrites the column on every
`model.save()`. Use it for cache invalidation. **Caveat: `queryset.update()`
bypasses `save()` and does NOT refresh `updated_at`.**

### Meta

```python
class Meta:
    abstract = True        # No DB table for BaseModel itself
    ordering = ["-created_at"]   # Newest-first default for all child models
```

`abstract = True` is critical — it means the three fields are injected directly
into each concrete subclass's migration, with no join table overhead.

### Usage

```python
from apps.core.models import BaseModel

class Product(BaseModel):
    name = models.CharField(max_length=200)
    # id, created_at, updated_at come for free
```

---

## response.py — Standard API Envelope

Every response — success or error — uses the same JSON shape:

```json
{
  "success": true,
  "message": "Product retrieved",
  "data":    { ... },
  "errors":  null,
  "meta":    { "total_count": 150, "page_size": 50, ... }
}
```

| Key | Type | When present |
|-----|------|--------------|
| `success` | boolean | Always |
| `message` | string | Always |
| `data` | any | Always (null on errors) |
| `errors` | object/null | Always (null on success) |
| `meta` | object | Only on paginated list responses |

### Functions

**`success_response(data, message, meta, status=200)`**
```python
return success_response(data=serializer.data, message="Product created.", status=201)
```

**`error_response(message, errors, status=400)`**
```python
return error_response(message="Validation failed.", errors=serializer.errors)
```

**`created_response(data, message)`** — shortcut for HTTP 201.

**`no_content_response(message)`** — shortcut for HTTP 204.

### Why a wrapper?

Without it, DRF views return raw data. Different views return different shapes.
The frontend has to handle `{"name": "x"}`, `{"data": {"name": "x"}}`, and
`{"results": [...]}` from the same API. The wrapper forces one shape everywhere.

---

## pagination.py — StandardResultsPagination

Registered globally in `settings.REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"]`.
Every list endpoint uses it automatically.

### Query params

| Param | Default | Max | Purpose |
|-------|---------|-----|---------|
| `?page` | 1 | — | Page number (1-based) |
| `?page_size` | 50 | 200 | Items per page |

### Meta block in response

```json
"meta": {
  "total_count": 150,
  "page_size":   50,
  "current_page": 2,
  "total_pages":  3,
  "next":     "http://localhost:8000/api/v1/products/?page=3",
  "previous": "http://localhost:8000/api/v1/products/?page=1"
}
```

`data` still holds the array of items; `meta` is the pagination envelope.
The frontend reads `meta.total_count` for "Showing 51–100 of 150 products".

---

## exceptions.py — custom_exception_handler

Registered in settings:
```python
REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "apps.core.exceptions.custom_exception_handler"
}
```

Without this, DRF errors return its own inconsistent shapes. Our handler
intercepts every exception and reformats to the standard envelope.

### What it handles

| Exception | Status | Notes |
|-----------|--------|-------|
| Serializer `ValidationError` | 400 | `errors` contains field-level dict |
| `AuthenticationFailed` | 401 | Generic message |
| `PermissionDenied` | 403 | Uses DRF's `detail` if present |
| `NotFound` | 404 | Generic message |
| `MethodNotAllowed` | 405 | Generic message |
| Unhandled exception | 500 | Logs full traceback; returns generic JSON |

### Field-level validation errors look like

```json
{
  "success": false,
  "message": "Bad request — please check your input.",
  "data": null,
  "errors": {
    "phone":    ["This phone number is already registered."],
    "password": ["This field is required."]
  }
}
```

---

## permissions.py — Role-Based Permission Classes

### User roles (defined on `accounts.User.role`)

| Role | Description |
|------|-------------|
| `admin` | Organisation-wide; can do everything |
| `manager` | Store manager; can manage users, products, reports |
| `cashier` | Counter staff; creates transactions, reads inventory |

### Permission classes

**`IsOrganisationAdmin`** — `role == "admin"` only.
Used on user management, organisation settings.

**`IsStoreManager`** — `role in ("admin", "manager")`.
Used on product CRUD, scheduled reports, write-offs, customer notes.

**`IsStoreCashier`** — `role in ("admin", "manager", "cashier")`.
Used on POS checkout, transactions, credits. Effectively: any authenticated staff.

**`IsReadOnly`** — `request.method in ("GET", "HEAD", "OPTIONS")`.
Allows browsing while blocking mutations.

### Combining permissions in views

```python
class ProductViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsStoreManager()]
        return [IsAuthenticated()]
```

---

## Design Decisions

1. **Abstract BaseModel** — Non-abstract inheritance creates a join table, adding an
   extra DB join to every query. Abstract inheritance inlines fields directly into
   each table with zero overhead.

2. **UUID4 not UUID1** — UUID1 encodes MAC address and timestamp, revealing server
   identity and insertion order. UUID4 is fully random and exposes nothing.

3. **`auto_now` vs manual** — `auto_now=True` on `updated_at` is convenient but has
   one known gap: `queryset.update()` bypasses Python's `save()` so `updated_at`
   stays stale after bulk operations. Acceptable trade-off for MVP; document it
   clearly so developers don't expect automatic refresh on bulk ops.

4. **Custom exception handler for 500s** — Without it, unhandled Python exceptions
   return an HTML error page even in a JSON API. Our handler logs the traceback and
   returns structured JSON so the frontend never gets unexpected HTML.

---

## Common Gotchas

- **UUID fields reject integer IDs.** Passing `/products/42` to a UUID-pk endpoint
  returns 404 with an "invalid UUID" error, not "product not found."

- **`updated_at` does NOT update on `queryset.update()`**. Use `instance.save()` if
  you need the timestamp to reflect the write.

- **`ordering = ["-created_at"]` is inherited by all child models.** If a child model
  needs a different default sort, override it explicitly with `ordering = ["name"]` or
  `ordering = []` in the child's `Meta`.

- **`success_response` defaults to HTTP 200.** Always pass `status=201` for creates
  and `status=204` for deletes that return no content.
