# apps/inventory — Products, Categories, Suppliers, and Stock

## What this app does

The `inventory` app manages the store's product catalogue and all stock movements. It covers four entities: `Category` (the filter groupings shown as pills in the UI), `Supplier` (the vendors who supply products), `Product` (the individual SKU with price, cost, and stock levels), and `StockAdjustment` (an immutable audit log of every change to a product's stock count).

Every sale processed through the POS deducts stock from the relevant products via `StockAdjustment` records. Every manual restock, damage write-off, or opening balance also creates `StockAdjustment` records. This means inventory has a complete, permanent, traceable history of every unit that ever entered or left the store. The `Product.stock` field is always the sum of all `StockAdjustment.quantity_change` values for that product — but rather than recalculating this on every read, the actual stock count is maintained as a cached integer on the model itself.

## Where it fits in the system

`inventory` depends on: `apps.core` (BaseModel), `apps.accounts` (Store FK, User FK for `performed_by`).

Apps that depend on `inventory`:
- `transactions` — reads `Product` to build `TransactionLine` records and deducts stock during `CompleteSaleView._process_sale()`.
- `analytics` — reads `Product.stock` and `Product.min_stock` for the low-stock widget; reads `TransactionLine` (which references `Product`) for product performance analytics.
- `ai` — reads `Product` directly for low-stock context in the system prompt.

---

## Data Models

### Category

**Purpose:** Product groupings shown as filter pills in the inventory UI. Examples: Grocery, Household, Beverage, Cosmetics, Bakery, Snacks. The "All" pill is a frontend construct — no "All" category exists in the database.

**Fields:**

| Field | Type | Details |
|-------|------|---------|
| `id` | UUIDField | PK from BaseModel |
| `name` | CharField(100) | Category name shown in filter pills. `unique=True` globally. |
| `description` | TextField | Optional internal description of what belongs in this category. |
| `sort_order` | PositiveSmallIntegerField | Controls display order in the filter pills (lower = first). Default 0. |
| `created_at` | DateTimeField | Inherited from BaseModel. |

**Meta:** `ordering = ["sort_order", "name"]`. Categories without an explicit sort_order fall back to alphabetical.

**Relationships:** Has many `Product` records via `products` related_name.

**Note:** Categories are managed through the Django admin only — there is no public API endpoint to create/edit/delete categories. The `CategoryViewSet` is read-only.

---

### Supplier

**Purpose:** Vendors who supply products to the store. Examples: Bakhresa Co., Unilever EA, Coca-Cola Kwanza, Tanga Fresh. Suppliers are referenced on products and shown in the product detail view.

**Fields:**

| Field | Type | Details |
|-------|------|---------|
| `id` | UUIDField | PK from BaseModel |
| `name` | CharField(200) | Company name, e.g. "Unilever EA". |
| `phone` | CharField(50) | Primary contact phone for ordering. |
| `email` | EmailField | Email for sending purchase orders. |
| `address` | TextField | Supplier address. |
| `notes` | TextField | Internal notes: payment terms, lead time, discount conditions. |
| `is_active` | BooleanField | Inactive suppliers are hidden from product dropdowns. Default True. |
| `created_at` | DateTimeField | Inherited. |
| `updated_at` | DateTimeField | Inherited. |

**Meta:** `ordering = ["name"]`.

**Soft-delete:** `SupplierViewSet.destroy()` sets `is_active=False` rather than hard-deleting. Active products linked to this supplier retain their FK — they just won't appear in "active suppliers" dropdowns.

---

### Product

**Purpose:** A sellable SKU in a store's inventory. This is the central entity of the entire POS: every transaction line, stock adjustment, AI restock suggestion, and analytics chart ultimately derives from the Product table.

**Important design note:** In the MVP, stock levels (`stock`, `min_stock`, `max_stock`) are stored directly on the Product row rather than in a separate `StockLevel` table. This means each Product can only exist in one store. A future multi-store expansion would need a `StockLevel(product, store, stock, min_stock, max_stock)` table — the `Product.store` FK would become a `Product.organisation` FK.

**All prices are stored as TZS integers (no sub-units).** Tanzania Shillings do not have cents.

**Fields:**

| Field | Type | Details |
|-------|------|---------|
| `id` | UUIDField | PK from BaseModel |
| `store` | ForeignKey(Store) | The store this product belongs to. `CASCADE` delete. All product queries are scoped by this field. |
| `name` | CharField(300) | Product name, e.g. "Unga wa Sembe 10kg". |
| `sku` | CharField(50) | Stock Keeping Unit code, e.g. "UWS-10". Unique within a store. |
| `barcode` | CharField(100) | EAN-13 or similar barcode for scanner input in POS. Optional. |
| `category` | ForeignKey(Category, nullable) | Product category for filter pills. `SET_NULL` on delete so products survive category deletions. |
| `supplier` | ForeignKey(Supplier, nullable) | Primary supplier. `SET_NULL` on delete. |
| `unit` | CharField(20) | Unit of measure: "pcs", "bag", "btl", "jerry", "pack", "tub", etc. Default "pcs". |
| `price` | PositiveIntegerField | Selling price in TZS (VAT-inclusive). What the customer pays. Must be > 0. |
| `cost` | PositiveIntegerField | Purchase/landed cost in TZS. What the store paid the supplier. Must be > 0 and < `price`. |
| `stock` | IntegerField | Current units on hand. Signed integer — can go negative (overselling allowed). Default 0. |
| `min_stock` | PositiveIntegerField | Reorder point. Low stock alert fires when `stock <= min_stock`. Default 0. |
| `max_stock` | PositiveIntegerField | Maximum capacity. Used as the scale for the stock bar visualization in the UI. Default 100. |
| `weekly_sold` | PositiveIntegerField | Average units sold per week. Updated nightly by analytics. Used by AI for restock suggestions. Default 0. |
| `last_restock_at` | DateField (nullable) | Date of the most recent stock replenishment. |
| `color` | CharField(20) | Color scheme key for the product avatar thumbnail: `indigo`, `amber`, `rose`, `lime`, `emerald`, `violet`, `cyan`. Default "indigo". |
| `is_active` | BooleanField | Inactive products are hidden from POS and inventory lists. Default True. |
| `created_at` | DateTimeField | Inherited. |
| `updated_at` | DateTimeField | Inherited. |

**Properties:**

- `margin_pct` — `(price - cost) / price * 100` rounded to 1 decimal. Shown in the inventory table "MARGIN" column. Returns 0.0 if `price == 0`.

- `stock_status` — Returns a string matching the UI status badge labels:
  - `"out"` — `stock == 0`
  - `"critical"` — `stock > 0` and `stock <= min_stock * 0.4`
  - `"low"` — `stock > 0` and `stock <= min_stock`
  - `"active"` — everything else

- `days_of_stock` — Estimated days of stock remaining based on `weekly_sold`. `stock / (weekly_sold / 7)`. Returns `None` if `weekly_sold == 0` (velocity unknown). Used by the AI to estimate urgency of restocking.

**Validation in serializer:**
- `price > 0`
- `cost > 0`
- `cost < price` — negative margin is treated as a data entry error. A product cannot cost more than its selling price.

**Meta:** `ordering = ["name"]`. `unique_together = [("store", "sku")]` — SKU must be unique within a store but not globally.

---

### StockAdjustment

**Purpose:** An immutable audit record of every change to a product's stock level. This is created automatically in these scenarios:
- **sale** — when a POS transaction is completed (`TransactionViewSet._process_sale`)
- **refund** — when a transaction is refunded and stock is restored
- **manual** — when a manager manually adjusts stock via the `/adjust-stock/` endpoint
- **restock** — when a supplier delivery is recorded (future feature; can also be done via manual with type=restock)
- **damage** — when products are written off as damaged or expired
- **opening** — the initial stock count when a product is first created

StockAdjustment records are never edited or deleted. They form a complete ledger from which current stock could theoretically be reconstructed.

**Fields:**

| Field | Type | Details |
|-------|------|---------|
| `id` | UUIDField | PK from BaseModel |
| `product` | ForeignKey(Product) | Which product changed. `CASCADE` delete — adjustments are deleted if the product is hard-deleted (but products are soft-deleted, so this rarely fires). |
| `adjustment_type` | CharField(20) | One of: `"sale"`, `"restock"`, `"manual"`, `"refund"`, `"damage"`, `"opening"`. |
| `quantity_change` | IntegerField | Units added (+) or removed (-). Cannot be 0. |
| `quantity_before` | IntegerField | Stock level immediately before this adjustment. |
| `quantity_after` | IntegerField | Stock level immediately after. Should equal `quantity_before + quantity_change`. |
| `reference` | CharField(100) | Reference document: TXN number, purchase order, etc. Used to link adjustments back to transactions. |
| `performed_by` | ForeignKey(User, nullable) | User who made this adjustment. `SET_NULL` on delete. Null for system-generated adjustments. |
| `note` | TextField | Reason for adjustment. Required for `"manual"` type adjustments. |
| `created_at` | DateTimeField | Inherited — the timestamp of when the adjustment occurred. |

**Meta:** `ordering = ["-created_at"]`. No `updated_at` is needed since these records are immutable.

---

## API Endpoints

### GET `/api/v1/inventory/categories/`

**View:** `CategoryViewSet` (list)
**Auth:** `IsAuthenticated`
**Pagination:** Disabled (few categories, always return all)

Response `data`: list of category objects.
```json
[
  { "id": "uuid", "name": "Grocery", "description": "", "sort_order": 1, "count": 24, "created_at": "..." },
  { "id": "uuid", "name": "Household", "description": "", "sort_order": 2, "count": 12, "created_at": "..." }
]
```

`count` is a live count of active products in each category — used for the filter pill badge "(24)". Computed via `obj.products.filter(is_active=True).count()`.

---

### GET `/api/v1/inventory/categories/{id}/`

**View:** `CategoryViewSet` (retrieve)
**Auth:** `IsAuthenticated`

Returns a single category with `count`.

---

### GET/POST `/api/v1/inventory/suppliers/`

**View:** `SupplierViewSet`
**Auth:** GET: `IsAuthenticated`; POST: `IsAuthenticated`, `IsStoreManager`

**GET** — Returns active suppliers only (`is_active=True`). Supports `?search=Unilever` (searches `name`, `email`, `phone`).

**POST** — Create a new supplier. Returns 201 with the created supplier.

Request body:
```json
{
  "name": "Unilever EA",
  "phone": "+254 20 123 4567",
  "email": "orders@unilever-ea.com",
  "address": "Industrial Area, Nairobi",
  "notes": "Payment terms: 30 days. Minimum order: 50k TZS."
}
```

---

### GET/PATCH/DELETE `/api/v1/inventory/suppliers/{id}/`

**View:** `SupplierViewSet`
**Auth:** `IsAuthenticated`, `IsStoreManager`

**DELETE** — Soft-delete: sets `is_active=False`. The supplier's products remain linked.

---

### GET `/api/v1/inventory/products/`

**View:** `ProductViewSet` (list)
**Auth:** `IsAuthenticated`

Returns paginated list of products scoped to `request.user.store`. Defaults to showing only active products.

**Query parameters:**

| Param | Example | Effect |
|-------|---------|--------|
| `?category=Grocery` | `?category=Grocery` | Filter by category name (case-insensitive). Use `?category=all` or omit to see all categories. |
| `?status=low` | `?status=low` | Only products at or below `min_stock` (stock > 0). |
| `?status=out` | `?status=out` | Only products with `stock == 0`. |
| `?status=critical` | `?status=critical` | Only products with `stock <= min_stock * 0.4`. |
| `?is_active=true` | `?is_active=true` | Show only active products (default behavior). |
| `?is_active=false` | `?is_active=false` | Show only archived products. |
| `?search=unga` | `?search=unga` | Full-text search across `name`, `sku`, `barcode`. |
| `?ordering=-weekly_sold` | `?ordering=-weekly_sold` | Sort by most sold (for dashboard top products widget). |
| `?minimal=true` | `?minimal=true` | Return `ProductMinimalSerializer` (id, name, sku, price, color, stock_status) — used by POS grid. |
| `?page_size=6` | `?page_size=6` | Return only 6 items (used by dashboard top products). |

Response data per product includes all fields including `margin_pct`, `stock_status`, `days_of_stock`, `category_name`, `supplier_name`.

**UI usage:** `/inventory` page, POS product grid, Dashboard top products widget.

---

### POST `/api/v1/inventory/products/`

**View:** `ProductViewSet` (create)
**Auth:** `IsAuthenticated`, `IsStoreManager`

Creates a new product. The `store` field is injected server-side from `request.user.store_id` — clients cannot specify which store.

Request body:
```json
{
  "name": "Unga wa Sembe 10kg",
  "sku": "UWS-10",
  "barcode": "6160100012413",
  "category": "category-uuid",
  "supplier": "supplier-uuid",
  "unit": "bag",
  "price": 28500,
  "cost": 22000,
  "stock": 50,
  "min_stock": 10,
  "max_stock": 200,
  "color": "amber"
}
```

Returns 201 with the full `ProductSerializer` response.

**Validation errors:**
- `price <= 0` → `"Selling price must be greater than zero."`
- `cost <= 0` → `"Cost must be greater than zero."`
- `cost >= price` → `"Cost must be less than the selling price."`
- Duplicate `sku` within the store → Django unique_together constraint error.

---

### GET `/api/v1/inventory/products/{id}/`

**View:** `ProductViewSet` (retrieve)
**Auth:** `IsAuthenticated`

Returns the full `ProductSerializer` response for a single product. **UI usage:** `/inventory/[id]` detail page.

---

### PATCH `/api/v1/inventory/products/{id}/`

**View:** `ProductViewSet` (partial_update)
**Auth:** `IsAuthenticated`, `IsStoreManager` (inferred from permissions on the ViewSet)

Partially update product fields. Returns the updated product.

---

### DELETE `/api/v1/inventory/products/{id}/`

**View:** `ProductViewSet` (destroy)
**Auth:** `IsAuthenticated`, `IsStoreManager`

Soft-delete: sets `is_active=False`. The product no longer appears in POS or inventory lists. Historical transaction lines that reference this product are unaffected.

---

### POST `/api/v1/inventory/products/{id}/adjust-stock/`

**View:** `ProductViewSet.adjust_stock` (extra action)
**Auth:** `IsAuthenticated`, `IsStoreManager`

Perform a manual stock adjustment. Both the `Product.stock` update and the `StockAdjustment` record creation happen inside a `db_transaction.atomic()` block.

Request body:
```json
{
  "quantity_change": -5,
  "note": "3 bags damaged by water leak, 2 expired"
}
```

- `quantity_change` — signed integer, cannot be 0. Positive adds stock, negative removes it.
- `note` — required explanation string (max 500 chars).

Response: the updated `ProductSerializer` response with the new stock count.

**Errors:**
- 400 if `quantity_change == 0`
- 404 if product not found or not in this store

**UI usage:** "Stock adjustment" button on `/inventory/[id]` detail page.

---

### GET `/api/v1/inventory/products/{id}/adjustments/`

**View:** `ProductViewSet.adjustments` (extra action)
**Auth:** `IsAuthenticated`

Returns the full stock movement history for a product, paginated, newest first.

Response per adjustment:
```json
{
  "id": "uuid",
  "product": "product-uuid",
  "product_name": "Unga wa Sembe 10kg",
  "product_sku": "UWS-10",
  "adjustment_type": "sale",
  "quantity_change": -2,
  "quantity_before": 50,
  "quantity_after": 48,
  "reference": "TXN-2043",
  "note": "",
  "performed_by": 42,
  "performed_by_name": "Hamisi Mwakapaga",
  "created_at": "2026-05-26T09:15:00Z"
}
```

**UI usage:** Stock history tab on `/inventory/[id]` detail page.

---

### GET `/api/v1/inventory/products/low-stock/`

**View:** `ProductViewSet.low_stock` (extra action, detail=False)
**Auth:** `IsAuthenticated`

Returns all active products where `stock <= min_stock`, ordered by `stock` ascending (most urgent first). Not paginated — returns all at once.

Response includes a `meta.count` field with the number of products returned.

**UI usage:** Dashboard "Low stock" widget, inventory page AI nudge banner, AI service context building.

---

## Admin

Inventory models are registered in the Django admin (via `admin.py` which is not explicitly listed but follows the standard `@admin.register(Model)` pattern). The admin allows managers to:
- Create and manage categories (the only way to do so — no API write endpoint)
- Create and manage suppliers
- View and edit products
- View stock adjustment history

---

## Design Decisions

- **Stock stored as integer on Product, not summed from adjustments:** Computing `SUM(quantity_change)` over all `StockAdjustment` records on every product query would be prohibitively slow for a store with 500+ products and thousands of daily transactions. The cached `stock` integer is updated atomically alongside each `StockAdjustment` creation.

- **`stock` is a signed IntegerField:** Overselling is allowed (stock can go negative). This is a deliberate design choice for the African retail context where stock counts may be inaccurate and blocking a sale because of a potential system error would be worse than allowing the sale to complete.

- **Price snapshots on TransactionLine (not Product):** Product prices change over time. TransactionLine stores `unit_price` and `unit_cost` at the time of sale. This means historical profit calculations remain accurate even after prices are updated. The Product model is the "current price" while TransactionLine is the "historical price at sale."

- **`ProductMinimalSerializer` for POS grid:** The POS product grid needs to load quickly. The `?minimal=true` query param returns only `id`, `name`, `sku`, `price`, `color`, `stock_status` — omitting heavy computed fields and nested objects.

- **`unique_together = [("store", "sku")]` not global uniqueness:** The same SKU code can exist in different stores. A chain might use the same SKU numbering system across all branches.

---

## Common Gotchas / Debugging Tips

- **`product.save(update_fields=["stock", "updated_at"])` — always include `"updated_at"`.** Django's `auto_now=True` only fires on full `save()` calls or when you explicitly include the field in `update_fields`. Many places in the codebase include `"updated_at"` explicitly for this reason.

- **`get_queryset()` uses `store=self.request.user.store`.** If the user has no store (`store=None`), this will return `Product.objects.filter(store=None)` which produces an empty queryset instead of an error. This is intentional — a storeless user simply sees no products. If a view should error instead, it should check `request.user.store` explicitly before proceeding.

- **The `adjust_stock` action uses `db_transaction.atomic()`.** If the `StockAdjustment.objects.create()` call fails after `product.stock` has already been updated, both operations roll back. This is correct behavior. However, if you add logic between the two operations that can raise exceptions, be careful about what happens on rollback.

- **`days_of_stock` returns `None` when `weekly_sold == 0`.** Any product that has never been sold or whose `weekly_sold` has not been updated will return `None`. Serializer field `allow_null=True` handles this correctly, but frontend code must handle the null case.

- **Category `count` is a live query, not cached.** Each category in the list response runs `obj.products.filter(is_active=True).count()`. For a list of 7 categories, this is 7 extra queries. If category count performance becomes an issue, this should be replaced with `annotate(count=Count("products", filter=Q(products__is_active=True)))` on the queryset.

- **`?status=critical` uses a raw `ExpressionWrapper`.** The critical status filter (`stock <= min_stock * 0.4`) uses Django ORM expressions rather than Python-level filtering. This is correct for performance but note that it computes `min_stock * 0.4` as a FloatField in the database. Products with `min_stock = 0` will match the critical filter when `stock <= 0`, which overlaps with the `out` status.
