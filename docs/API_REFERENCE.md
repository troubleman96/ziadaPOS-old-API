# API Reference

Base URL: `http://localhost:8000/api/v1/`  
All responses use the standard envelope:

```json
{
  "success": true | false,
  "message": "Human-readable description",
  "data":    { ... } | [ ... ] | null,
  "errors":  null | { "field": ["error text"] },
  "meta":    { "count": 100, "page": 1, ... }
}
```

All requests require `Authorization: Bearer <access_token>` unless marked **public**.

---

## Authentication

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/auth/register/` | Public | Self-registration → org + store + owner + trial |
| POST | `/auth/login/` | Public | Phone + password → JWT tokens |
| POST | `/auth/refresh/` | Public | Refresh token → new access token |
| POST | `/auth/verify/` | Public | Verify a token is valid |

---

## Current User

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/accounts/me/` | Owner/Staff | Profile + subscription + verification status |
| PATCH | `/accounts/me/` | Owner/Staff | Update profile |
| POST | `/accounts/me/change-password/` | Owner/Staff | Change password |

---

## Organisation

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/accounts/organisation/` | Owner | Get org settings |
| PATCH | `/accounts/organisation/` | Owner | Update org settings |

---

## Users / Staff

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/accounts/users/` | Owner | List staff (filter by store, role, status) |
| POST | `/accounts/users/` | Owner | Create staff member |
| GET | `/accounts/users/{id}/` | Owner | Staff detail + stats |
| PATCH | `/accounts/users/{id}/` | Owner | Update staff (shift, permissions, role) |
| DELETE | `/accounts/users/{id}/` | Owner | Deactivate staff (soft delete) |
| GET | `/accounts/users/{id}/stats/` | Owner | Performance stats for one staff |
| GET | `/accounts/users/kpis/` | Owner | Store-level staff KPIs |

---

## Stores

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/stores/` | Owner/Staff | List org's stores with live KPIs |
| POST | `/stores/` | Owner | Create store (enforces max_stores limit) |
| GET | `/stores/stats/` | Owner/Staff | Org-level KPI header |
| GET | `/stores/{id}/` | Owner/Staff | Store detail (week chart + staff roster) |
| PATCH | `/stores/{id}/` | Owner | Update store settings |
| DELETE | `/stores/{id}/` | Owner | Deactivate store (soft delete) |
| GET | `/stores/{id}/staff/` | Owner/Staff | Staff roster for one store |
| GET | `/stores/{id}/week/` | Owner/Staff | 7-day revenue breakdown |
| PATCH | `/stores/{id}/status/` | Owner | Quick status toggle (open/closed/paused) |

**Account-level store CRUD (same model, different URL):**

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/accounts/stores/` | Owner | List stores (simpler, no KPIs) |
| POST | `/accounts/stores/` | Owner | Create store (enforces limit) |
| GET | `/accounts/stores/{id}/` | Owner | Store detail |
| PATCH | `/accounts/stores/{id}/` | Owner | Update store |

---

## Subscriptions

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/subscriptions/plans/` | **Public** | List active pricing plans |
| GET | `/subscriptions/plans/{id}/` | **Public** | Plan detail |
| POST | `/subscriptions/plans/` | Admin | Create a plan |
| PATCH | `/subscriptions/plans/{id}/` | Admin | Update a plan |
| DELETE | `/subscriptions/plans/{id}/` | Admin | Deactivate a plan |
| GET | `/subscriptions/my-subscription/` | Owner | Own subscription status |
| GET | `/subscriptions/store-limit/` | Owner | Can-add-store check + pricing |
| GET | `/subscriptions/all/` | Admin | All subscriptions |
| GET | `/subscriptions/all/{id}/` | Admin | Subscription detail |
| POST | `/subscriptions/all/{id}/activate/` | Admin | Confirm payment + activate |
| PATCH | `/subscriptions/all/{id}/extra-stores/` | Admin | Grant extra store slots |

---

## Inventory

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/inventory/categories/` | Owner/Staff | Product categories |
| GET/PATCH/DELETE | `/inventory/categories/{id}/` | Owner | Category detail |
| GET | `/inventory/products/` | Owner/Staff | Product list (filter by category, status, search) |
| POST | `/inventory/products/` | Owner | Create product |
| GET/PATCH | `/inventory/products/{id}/` | Owner/Staff | Product detail/update |
| DELETE | `/inventory/products/{id}/` | Owner | Archive product |
| POST | `/inventory/products/{id}/adjust-stock/` | Owner | Manual stock adjustment |
| GET | `/inventory/stock-adjustments/` | Owner | Stock audit log |

---

## Transactions (POS)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/transactions/` | Owner/Staff | Transaction list (filter by status, method, date) |
| GET | `/transactions/{id}/` | Owner/Staff | Transaction detail with lines |
| POST | `/transactions/{id}/refund/` | Owner/Staff (can_refund) | Refund a transaction |
| GET | `/transactions/summary/` | Owner | Aggregate KPI stats |
| POST | `/transactions/complete-sale/` | Owner/Staff | Process POS cart → create transaction |

---

## Credits (Madeni)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/credits/credit-tabs/` | Owner/Staff | Outstanding credit list |
| GET | `/credits/credit-tabs/{id}/` | Owner/Staff | Credit detail with payments |
| POST | `/credits/credit-payments/` | Owner/Staff | Record a payment |
| GET | `/credits/credit-messages/` | Owner/Staff | Communication timeline |
| POST | `/credits/credit-notes/` | Owner/Staff | Add internal note |

---

## Customers

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/customers/` | Owner/Staff | Customer list (filter by segment, search) |
| POST | `/customers/` | Owner | Create customer |
| GET/PATCH | `/customers/{id}/` | Owner/Staff | Customer detail/update |
| DELETE | `/customers/{id}/` | Owner | Soft-delete customer |
| GET | `/customers/{id}/transactions/` | Owner | Customer transaction history |
| GET | `/customers/{id}/credit/` | Owner | Customer credit status |
| GET | `/customers/summary/` | Owner | Segment counts and totals |

---

## Analytics

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/analytics/overview/` | Owner/Staff | KPIs + trend + payment mix |
| GET | `/analytics/trend/` | Owner/Staff | Revenue trend by day |
| GET | `/analytics/summary/` | Owner/Staff | Totals for a date range |
| GET | `/analytics/payment-mix/` | Owner/Staff | Payment method breakdown |
| GET | `/analytics/top-products/` | Owner/Staff | Best-selling products |
| GET | `/analytics/breakdown/` | Owner/Staff | Category/DOW/hourly breakdown |
| GET | `/analytics/product-performance/` | Owner | Product-level stats |
| GET | `/analytics/customers/` | Owner | Customer visit and segment analytics |
| GET | `/analytics/cashflow/` | Owner | Cash in/out summary |
| GET | `/analytics/dashboard/` | Owner/Staff | Combined dashboard data |

---

## Reports

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/reports/types/` | Owner/Staff | Available report types |
| POST | `/reports/generate/` | Owner | Generate report (CSV or JSON) |
| GET | `/reports/exports/` | Owner | Export history list |
| GET | `/reports/exports/{id}/download/` | Owner | Re-download a previous export |
| GET | `/reports/scheduled/` | Owner | Scheduled report list |
| POST | `/reports/scheduled/` | Owner | Create scheduled report |
| PATCH | `/reports/scheduled/{id}/` | Owner | Update/toggle scheduled report |
| DELETE | `/reports/scheduled/{id}/` | Owner | Delete scheduled report |

---

## AI Chat

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/ai/conversations/` | Owner/Staff | List user's conversations |
| POST | `/ai/chat/` | Owner/Staff | Start new conversation |
| GET | `/ai/conversations/{id}/` | Owner/Staff | Full conversation + messages |
| PATCH | `/ai/conversations/{id}/` | Owner/Staff | Rename/archive |
| POST | `/ai/conversations/{id}/chat/` | Owner/Staff | Continue conversation |
| GET | `/ai/suggestions/` | Owner/Staff | Contextual prompt suggestions |

---

## Suppliers

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/suppliers/suppliers/` | Owner | Supplier list/create |
| GET/PATCH | `/suppliers/suppliers/{id}/` | Owner | Supplier detail/update |
| GET | `/suppliers/suppliers/{id}/deliveries/` | Owner | Delivery history |
| POST | `/suppliers/supplier-deliveries/` | Owner | Record delivery |
| PATCH | `/suppliers/supplier-deliveries/{id}/` | Owner | Update delivery |
| POST | `/suppliers/supplier-payments/` | Owner | Record payment |
| PATCH | `/suppliers/supplier-payments/{id}/` | Owner | Update payment |

---

## AI Credits

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/accounts/ai-credits/` | Owner/Staff | Current month AI credit usage |

---

## Notebook

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/notebook/notes/` | Owner/Staff | Notes list/create |
| GET/PATCH/DELETE | `/notebook/notes/{id}/` | Owner/Staff | Note detail/update/delete |
| GET | `/notebook/notes/tags/` | Owner/Staff | Available tags |

---

## Staff management

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/staff/` | Owner | Staff list with schedule |
| POST | `/staff/` | Owner | Create staff member |
| GET/PATCH | `/staff/{id}/` | Owner | Staff detail/update |
| DELETE | `/staff/{id}/` | Owner | Deactivate staff |
| PATCH | `/staff/{id}/permissions/` | Owner | Update staff permissions |
| GET | `/staff/{id}/stats/` | Owner | Staff performance stats |

---

## Common query parameters

Most list endpoints support:

| Param | Type | Description |
|-------|------|-------------|
| `search` | string | Full-text search |
| `page` | int | Page number (default 1) |
| `page_size` | int | Results per page (default 50, max 200) |
| `ordering` | string | Field to sort by (prefix `-` for descending) |

Date range filters (where applicable):

| Param | Format | Description |
|-------|--------|-------------|
| `range` | `7d`, `30d`, `90d`, `month`, `ytd` | Preset date range |
| `date_from` | `YYYY-MM-DD` | Start date (use with `date_to`) |
| `date_to` | `YYYY-MM-DD` | End date |
