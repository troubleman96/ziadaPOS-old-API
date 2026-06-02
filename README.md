# Ziada POS — Backend API

A Django REST Framework backend powering the Ziada POS (Point of Sale) web application for Tanzanian retail shops. Bilingual (Swahili/English) AI-assisted business intelligence via OpenRouter GPT-4o-mini.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Quick Start](#quick-start)
3. [Project Structure](#project-structure)
4. [Apps Overview](#apps-overview)
5. [Complete API Reference](#complete-api-reference)
6. [Authentication](#authentication)
7. [Standard Response Envelope](#standard-response-envelope)
8. [Data Model Map](#data-model-map)
9. [Key Design Decisions](#key-design-decisions)
10. [Environment Variables](#environment-variables)
11. [Running Tests](#running-tests)
12. [Tech Stack](#tech-stack)
13. [Development Guide](#development-guide)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Next.js Frontend                         │
│              http://localhost:3000                          │
└──────────────────────────┬──────────────────────────────────┘
                           │ JWT Bearer token
                           │ REST API calls
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              Django REST Framework Backend                   │
│              http://localhost:8000/api/v1/                  │
│                                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ accounts │ │inventory │ │transact. │ │   credits    │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │customers │ │analytics │ │ reports  │ │     ai       │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
│                      ┌───────────┐                          │
│                      │   core    │ (shared utilities)       │
│                      └───────────┘                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                 ┌─────────┴──────────┐
                 │                    │
          ┌──────▼──────┐    ┌────────▼────────┐
          │ PostgreSQL  │    │ OpenRouter API  │
          │  (database) │    │ (LLM gateway)   │
          └─────────────┘    └─────────────────┘
```

**Multi-tenant hierarchy:** Organisation → Store → User  
Each user belongs to one Store; all data is scoped to the Store.

---

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL (SQLite works for local development)
- OpenRouter API key (free tier available at https://openrouter.ai)

### 1. Set up virtual environment

```bash
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Minimum required `.env` for development:
```env
SECRET_KEY=your-secret-key-here
DEBUG=True
DATABASE_URL=                  # leave blank for SQLite
OPENROUTER_API_KEY=sk-or-...   # get one free at openrouter.ai
```

### 3. Database setup

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4. (Optional) Load sample data

```bash
python manage.py loaddata fixtures/sample_store.json
```

### 5. Run the development server

```bash
python manage.py runserver
```

- API: `http://localhost:8000/api/v1/`
- Admin: `http://localhost:8000/admin/`

---

## Project Structure

```
backend/
├── manage.py
├── requirements.txt
├── .env.example
│
├── ziada/                              # Django project configuration
│   ├── settings/
│   │   ├── base.py                     # Shared settings (all environments)
│   │   ├── development.py              # DEBUG=True, SQLite fallback
│   │   └── production.py              # PostgreSQL, HTTPS, no DEBUG
│   ├── urls.py                         # Root URL config (mounts all /api/v1/ routes)
│   ├── wsgi.py                         # WSGI entry point (gunicorn)
│   └── asgi.py                         # ASGI entry point (future WebSockets)
│
└── apps/
    ├── core/                           # Shared utilities (no domain logic)
    │   ├── models.py                   # BaseModel: UUID PK + timestamps
    │   ├── response.py                 # Standard API response envelope
    │   ├── pagination.py               # StandardResultsPagination
    │   ├── exceptions.py               # Custom exception handler
    │   └── permissions.py             # IsOrganisationAdmin, IsStoreManager, IsStoreCashier
    │
    ├── accounts/                       # Users, organisations, stores, AI credits
    │   ├── models.py                   # Organisation, Store, User, AICredit
    │   ├── api/
    │   │   ├── auth_urls.py            # JWT login/refresh/verify
    │   │   ├── urls.py                 # /accounts/ routes
    │   │   ├── views.py                # MeView, OrganisationView, UserViewSet, StoreViewSet
    │   │   └── serializers.py
    │   └── README.md
    │
    ├── inventory/                      # Products, categories, suppliers, stock
    │   ├── models.py                   # Category, Supplier, Product, StockAdjustment
    │   ├── signals.py
    │   ├── api/
    │   │   ├── urls.py                 # /inventory/ routes (DefaultRouter)
    │   │   ├── views.py                # CategoryViewSet, SupplierViewSet, ProductViewSet
    │   │   └── serializers.py
    │   └── README.md
    │
    ├── transactions/                   # Sales transactions, POS checkout, refunds
    │   ├── models.py                   # Transaction, TransactionLine
    │   ├── api/
    │   │   ├── urls.py                 # /transactions/ routes
    │   │   ├── views.py                # TransactionViewSet, CompleteSaleView
    │   │   └── serializers.py
    │   └── README.md
    │
    ├── credits/                        # Customer credit management (madeni)
    │   ├── models.py                   # CreditTab, CreditPayment, CreditMessage, CreditNote
    │   ├── api/
    │   │   ├── urls.py                 # /credits/ routes
    │   │   ├── views.py                # CreditsDashboardView, CustomerCreditProfileView, ...
    │   │   └── serializers.py
    │   └── README.md
    │
    ├── customers/                      # Customer directory, segments, loyalty
    │   ├── models.py                   # Customer
    │   ├── api/
    │   │   ├── urls.py                 # /customers/ routes
    │   │   ├── views.py                # CustomerViewSet
    │   │   └── serializers.py
    │   └── README.md
    │
    ├── analytics/                      # Pre-aggregated stats + analytics services
    │   ├── models.py                   # DailySummary
    │   ├── services.py                 # All analytics computation functions
    │   ├── signals.py                  # Transaction post_save → rebuild DailySummary
    │   ├── apps.py                     # AnalyticsConfig.ready() wires the signal
    │   ├── api/
    │   │   ├── urls.py                 # /analytics/ routes
    │   │   └── views.py                # 10 analytics views
    │   └── README.md
    │
    ├── reports/                        # Report generation, export history, scheduling
    │   ├── models.py                   # ScheduledReport, ReportExport
    │   ├── services.py                 # Report generators + CSV builder
    │   ├── api/
    │   │   ├── urls.py                 # /reports/ routes
    │   │   ├── views.py                # ReportTypesView, GenerateReportView, ...
    │   │   └── serializers.py
    │   └── README.md
    │
    └── ai/                             # Ziada AI chat (OpenRouter)
        ├── models.py                   # Conversation, Message
        ├── service.py                  # build_store_context, build_system_prompt, chat()
        ├── apps.py                     # AIConfig (label = "ai_app")
        ├── api/
        │   ├── urls.py                 # /ai/ routes
        │   ├── views.py                # ConversationListView, StartChatView, ...
        │   └── serializers.py
        └── README.md
```

---

## Apps Overview

| App | Purpose | Models | Key endpoints |
|-----|---------|--------|---------------|
| **core** | Shared utilities | `BaseModel` | (no endpoints) |
| **accounts** | Users, orgs, stores | `Organisation`, `Store`, `User`, `AICredit` | `/auth/`, `/accounts/` |
| **inventory** | Product catalogue + stock | `Category`, `Supplier`, `Product`, `StockAdjustment` | `/inventory/` |
| **transactions** | POS checkout + history | `Transaction`, `TransactionLine` | `/transactions/` |
| **credits** | Customer credit (madeni) | `CreditTab`, `CreditPayment`, `CreditMessage`, `CreditNote` | `/credits/` |
| **customers** | Customer directory | `Customer` | `/customers/` |
| **analytics** | Aggregated stats | `DailySummary` | `/analytics/` |
| **reports** | Report generation | `ScheduledReport`, `ReportExport` | `/reports/` |
| **ai** | AI chat assistant | `Conversation`, `Message` | `/ai/` |

**App dependency graph:**
```
core ← accounts ← inventory ← transactions ← credits
                               ↑                ↑
                           customers ──────────┘
                               ↑
                           analytics ← reports
                               ↑
                               ai
```

---

## Complete API Reference

All endpoints require `Authorization: Bearer <access_token>` unless marked otherwise.

### Authentication (`/api/v1/auth/`)

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| POST | `/auth/login/` | None | Exchange username+password for JWT tokens |
| POST | `/auth/refresh/` | None | Get new access token from refresh token |
| POST | `/auth/verify/` | None | Check if an access token is still valid |

**Login response:**
```json
{ "access": "eyJ...", "refresh": "eyJ..." }
```

---

### Accounts (`/api/v1/accounts/`)

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET/PATCH | `/accounts/me/` | Any | Current user profile + store |
| POST | `/accounts/me/change-password/` | Any | Change own password |
| GET | `/accounts/organisation/` | Any | Organisation details |
| GET/POST | `/accounts/users/` | Manager+ | List/create staff |
| GET/PATCH/DELETE | `/accounts/users/{id}/` | Manager+ | Staff CRUD |
| GET/POST | `/accounts/stores/` | OrgAdmin | List/create stores |
| GET/PATCH | `/accounts/stores/{id}/` | OrgAdmin | Store CRUD |

---

### Inventory (`/api/v1/inventory/`)

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/inventory/categories/` | Any | List all product categories |
| GET | `/inventory/categories/{id}/` | Any | Category detail |
| GET/POST | `/inventory/suppliers/` | Any/Manager+ | List or create suppliers |
| GET/PATCH/DELETE | `/inventory/suppliers/{id}/` | Manager+ | Supplier CRUD |
| GET | `/inventory/products/` | Any | List products (filtered, paginated) |
| POST | `/inventory/products/` | Any | Create product |
| GET | `/inventory/products/{id}/` | Any | Product detail |
| PATCH | `/inventory/products/{id}/` | Any | Update product |
| DELETE | `/inventory/products/{id}/` | Any | Soft-delete product |
| GET | `/inventory/products/low-stock/` | Any | Products below reorder point |
| POST | `/inventory/products/{id}/adjust-stock/` | Manager+ | Manual stock adjustment |
| GET | `/inventory/products/{id}/adjustments/` | Any | Stock movement history |

**Key product list filters:**
```
?category=Grocery          filter by category name
?status=low|out|critical   filter by stock status
?search=unga               search name/SKU/barcode
?ordering=-weekly_sold     sort by top sellers
?minimal=true              lean response for POS grid
?is_active=true/false      active/archived products
```

---

### Transactions (`/api/v1/transactions/`)

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| **POST** | `/transactions/complete-sale/` | Cashier+ | **POS checkout — core action** |
| GET | `/transactions/` | Any | List transactions (filtered, paginated) |
| GET | `/transactions/{id}/` | Any | Transaction detail with line items |
| POST | `/transactions/{id}/refund/` | Cashier+ | Refund a paid transaction |
| GET | `/transactions/summary/` | Any | Aggregate KPI stats |

**POS checkout payload:**
```json
POST /api/v1/transactions/complete-sale/
{
  "items": [
    { "product_id": "uuid", "qty": 2 },
    { "product_id": "uuid", "qty": 1 }
  ],
  "payment_method": "M-Pesa",
  "payment_reference": "QGT5K3AB",
  "discount_pct": "5.00",
  "till_number": "Till #1",
  "customer_id": null
}
```

Payment methods: `Cash`, `M-Pesa`, `Tigo Pesa`, `Bank`, `Credit`

---

### Credits (`/api/v1/credits/`)

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/credits/` | Any | Dashboard: KPIs + aging + customer list |
| GET | `/credits/customers/{id}/` | Any | Full customer credit profile |
| POST | `/credits/customers/{id}/record-payment/` | Cashier+ | Record a payment |
| POST | `/credits/customers/{id}/send-reminder/` | Cashier+ | Log a WhatsApp/call/SMS |
| POST | `/credits/customers/{id}/add-note/` | Cashier+ | Add internal staff note |
| POST | `/credits/tabs/{id}/write-off/` | Manager+ | Write off a credit tab |

---

### Customers (`/api/v1/customers/`)

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/customers/` | Any | List customers (segmented, filtered) |
| POST | `/customers/` | Manager+ | Add new customer |
| GET | `/customers/{id}/` | Any | Customer detail |
| PATCH | `/customers/{id}/` | Manager+ | Update customer info/segment |
| DELETE | `/customers/{id}/` | Manager+ | Soft-delete customer |
| GET | `/customers/summary/` | Any | KPI aggregate stats |

**Customer list filters:**
```
?segment=VIP|Regular|Occasional|New
?has_credit=true
?search=Fatuma
?ordering=-total_spent
```

---

### Analytics (`/api/v1/analytics/`)

All analytics endpoints support `?range=7d|30d|90d|ytd` or `?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`.

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/analytics/overview/` | KPIs + trend + payment mix + top products |
| GET | `/analytics/summary/` | KPIs only |
| GET | `/analytics/trend/` | Day-by-day revenue series |
| GET | `/analytics/payment-mix/` | Revenue by payment method |
| GET | `/analytics/top-products/` | Most sold products by revenue |
| GET | `/analytics/sales/` | Category revenue + DOW averages + hourly pattern |
| GET | `/analytics/products/` | Product performance table (margin, trend) |
| GET | `/analytics/customers/` | Visits, segments, retention cohorts, top customers |
| GET | `/analytics/cashflow/` | Daily inflow/COGS/net, running balance |
| GET | `/analytics/dashboard/` | All dashboard widgets in one call |

Extra params:
```
/analytics/products/?category=Grocery
/analytics/products/?sort=revenue|units|margin|profit
```

---

### Reports (`/api/v1/reports/`)

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/reports/types/` | Any | Available report types catalogue |
| POST | `/reports/generate/` | Any | Generate a report (CSV download or JSON) |
| GET | `/reports/exports/` | Any | Export history (History tab) |
| GET | `/reports/exports/{id}/download/` | Any | Re-download a past export |
| GET/POST | `/reports/scheduled/` | Any/Manager+ | List/create scheduled reports |
| PATCH/DELETE | `/reports/scheduled/{id}/` | Manager+ | Update or delete schedule |

**Generate report:**
```json
POST /api/v1/reports/generate/
{
  "report_type": "sales",
  "format": "csv",
  "range": "30d"
}
```

Report types: `sales`, `inventory`, `tax`, `credit`  
Formats: `csv` (file download), `json` (data for PDF rendering)  
Date ranges: `7d`, `30d`, `90d`, `month`, `ytd`, or explicit `date_from`+`date_to`

---

### AI Chat (`/api/v1/ai/`)

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/ai/conversations/` | Any | List chat history (sidebar) |
| POST | `/ai/chat/` | Any | Start a new conversation |
| GET | `/ai/conversations/{id}/` | Any | Get conversation with all messages |
| POST | `/ai/conversations/{id}/chat/` | Any | Continue a conversation |
| PATCH | `/ai/conversations/{id}/` | Any | Rename or archive |
| GET | `/ai/suggestions/` | Any | Contextual prompt suggestions + credit status |

---

## Authentication

Ziada uses JWT (JSON Web Tokens) via `djangorestframework-simplejwt`.

### Token lifetime

| Token | Default TTL | Configured by |
|-------|-------------|---------------|
| Access token | 60 minutes | `JWT_ACCESS_TOKEN_LIFETIME_MINUTES` |
| Refresh token | 7 days | `JWT_REFRESH_TOKEN_LIFETIME_DAYS` |

### Login flow

```
POST /api/v1/auth/login/
Body: { "username": "hamisi", "password": "..." }

Response:
{
  "access":  "eyJhbGciOiJIUzI1NiIsInR5...",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5..."
}
```

All subsequent requests include: `Authorization: Bearer {access}`

When the access token expires, use the refresh token:
```
POST /api/v1/auth/refresh/
Body: { "refresh": "eyJ..." }
Response: { "access": "eyJ..." }
```

**Token rotation:** Every refresh issues a new refresh token. The old one is blacklisted. If a refresh token is stolen and used, the legitimate user's next refresh attempt will fail (the stolen token was already rotated out).

---

## Standard Response Envelope

Every API response — success or error — uses the same JSON structure:

```json
{
  "success": true,
  "message": "Transaction TXN-2043 completed.",
  "data": { ... },
  "errors": null,
  "meta": {
    "total_count": 87,
    "page": 2,
    "page_size": 25,
    "total_pages": 4,
    "next": "http://localhost:8000/api/v1/transactions/?page=3",
    "previous": "http://localhost:8000/api/v1/transactions/?page=1"
  }
}
```

On error:
```json
{
  "success": false,
  "message": "Validation failed.",
  "data": null,
  "errors": {
    "price": ["Selling price must be greater than zero."],
    "sku": ["Product with this SKU already exists in this store."]
  },
  "meta": null
}
```

HTTP status codes follow REST conventions (200, 201, 204, 400, 403, 404, 500). The `success` boolean in the envelope always matches: true for 2xx, false for 4xx/5xx.

---

## Data Model Map

```
Organisation
  ├── Store (many stores per org)
  │   ├── User (many staff per store, role: cashier/manager/owner/admin)
  │   ├── Category (product groupings)
  │   ├── Supplier (vendors)
  │   ├── Product (SKUs with stock levels)
  │   │   └── StockAdjustment (immutable audit log of stock changes)
  │   ├── Customer (registered buyers)
  │   │   ├── CreditTab (one per credit sale)
  │   │   ├── CreditPayment (cash received from customer)
  │   │   ├── CreditMessage (WhatsApp/call logs)
  │   │   └── CreditNote (internal staff notes)
  │   ├── Transaction (one per sale)
  │   │   └── TransactionLine (one per product × qty in sale)
  │   ├── DailySummary (one per day, pre-aggregated stats)
  │   ├── ScheduledReport (recurring report configs)
  │   ├── ReportExport (audit trail of generated reports)
  │   └── Conversation (AI chat threads)
  │       └── Message (individual chat messages)
  └── AICredit (monthly AI token budget — one per org per month)
```

---

## Key Design Decisions

### 1. UUID Primary Keys

All application models inherit from `BaseModel` which uses `uuid.uuid4` as the primary key. Benefits:
- No enumeration attacks (`/customers/1/`, `/customers/2/` can be scraped; UUIDs cannot)
- Safe for future multi-master replication
- Can generate IDs client-side before inserting

**Exception:** `User` uses an integer PK inherited from `AbstractUser`. Changing this after migration would require a full DB reset.

### 2. TZS Integer Amounts

All monetary values are stored as plain Python `int` representing Tanzanian Shillings:
- `28500` = TZS 28,500
- No Decimal fields for amounts (avoids decimal/float confusion)
- No currency conversion (single-currency system)
- Tanzania has no sub-units (no "cents"), so integers are exactly correct

### 3. Price Snapshots on TransactionLine

`TransactionLine.unit_price` and `unit_cost` are stored at the time of sale and **never updated**. Product prices change — if we looked up the current price on historical transactions, profit figures would silently change whenever a price update occurred. Snapshots make financial history immutable.

### 4. Atomic POS Checkout

The entire `complete-sale` flow runs inside `@db_transaction.atomic`:
- Creates `Transaction`
- Creates N `TransactionLine` records
- Updates stock for N `Product` records
- Creates N `StockAdjustment` records
- Optionally creates `CreditTab`

Any failure (missing product, DB constraint violation) rolls back everything. No partial sales, no phantom revenue, no stuck stock counts.

### 5. Soft Deletes

Products and Customers are soft-deleted (`is_active = False`) instead of hard-deleted:
- Historical transactions referencing a soft-deleted product remain valid
- Historical transactions referencing a soft-deleted customer remain valid
- Credit tabs on soft-deleted customers remain visible to managers

### 6. DailySummary Pre-aggregation

`DailySummary` (one row per store per day) is updated via Django signal on every Transaction save. Analytics queries read from DailySummary (30–90 rows for a range) instead of scanning all Transaction rows. This keeps analytics fast as data volume grows.

### 7. AI Context Injection vs RAG

For MVP, the AI system prompt includes a structured text snapshot of live store data (today's revenue, low-stock items, credit customers, top products). This is simpler, faster, and more accurate than vector-search RAG for the data volumes typical of a corner shop. Context size is ~800-1200 tokens, well within GPT-4o-mini's 128k window.

### 8. Report Regeneration vs Stored Files

`ReportExport` stores only metadata (`date_from`, `date_to`, `report_type`). File content is regenerated on every download. This keeps the DB lean and ensures re-downloads reflect any data corrections since the original export.

### 9. Credit Payment Distribution

Payments are linked to Customer, not to a specific CreditTab. The `_apply_payment_to_tabs()` function distributes payments oldest-first across open tabs. This matches real-world practice where customers pay a lump sum without specifying which tab it covers.

### 10. Tanzania-specific Considerations

- **Timezone:** All code uses `Africa/Dar_es_Salaam` (UTC+3). `USE_TZ=True` stores everything in UTC; timezone conversion is done at display time or via DB expressions.
- **VAT:** 18% (configurable via `TZ_VAT_RATE` setting)
- **Payment methods:** M-Pesa and Tigo Pesa are first-class payment methods (not "other mobile money")
- **Language:** AI responds in Swahili or English based on user input language

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | ✅ | — | Django secret key. Generate with `python -c "import secrets; print(secrets.token_hex(50))"` |
| `DEBUG` | — | `False` | Set to `True` for development |
| `ALLOWED_HOSTS` | — | `localhost,127.0.0.1` | Comma-separated allowed hosts |
| `DATABASE_URL` | — | SQLite | PostgreSQL URL: `postgres://user:pass@host/dbname` |
| `CORS_ALLOWED_ORIGINS` | — | `http://localhost:3000` | Frontend origin(s) |
| `OPENROUTER_API_KEY` | ✅ (AI) | `""` | OpenRouter API key |
| `OPENROUTER_MODEL` | — | `openai/gpt-4o-mini` | LLM model ID |
| `OPENROUTER_SITE_URL` | — | `http://localhost:3000` | Sent as HTTP-Referer to OpenRouter |
| `OPENROUTER_SITE_NAME` | — | `Ziada POS` | Sent as X-Title to OpenRouter |
| `JWT_ACCESS_TOKEN_LIFETIME_MINUTES` | — | `60` | Access token TTL |
| `JWT_REFRESH_TOKEN_LIFETIME_DAYS` | — | `7` | Refresh token TTL |

---

## Running Tests

```bash
# Run all tests
python manage.py test apps

# Run a specific app
python manage.py test apps.transactions
python manage.py test apps.credits
python manage.py test apps.reports

# With verbosity
python manage.py test apps --verbosity=2

# With coverage
pip install coverage
coverage run manage.py test apps
coverage report --show-missing
coverage html  # open htmlcov/index.html
```

Tests use `pytest-django` and `factory-boy` for fixtures. Each app has its own `tests/` directory with a `test_<app>.py` file.

---

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Framework | Django + Django REST Framework | 5.0.6 + 3.15 |
| Authentication | djangorestframework-simplejwt (JWT) | 5.x |
| Database | PostgreSQL (SQLite in dev) | 15+ |
| AI / LLM | OpenRouter → GPT-4o-mini via openai SDK | — |
| CORS | django-cors-headers | 4.x |
| Filtering | django-filter | 24.x |
| Config | python-decouple (.env parsing) | 3.x |
| Testing | pytest-django + factory-boy | — |
| Currency | TZS integers (no Decimal) | — |
| Timezone | Africa/Dar_es_Salaam (UTC+3) | — |
| VAT | 18% (`TZ_VAT_RATE = 0.18`) | — |

---

## Development Guide

### Adding a new app

1. Create the app: `python manage.py startapp myapp apps/myapp`
2. Add to `LOCAL_APPS` in `settings/base.py`
3. Add a URL prefix in `ziada/urls.py`
4. Create `apps/myapp/api/` with `urls.py`, `views.py`, `serializers.py`
5. Inherit all models from `apps.core.models.BaseModel`
6. Write tests in `apps/myapp/tests/test_myapp.py`
7. Register models in `apps/myapp/admin.py`

### Running migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### Rebuilding analytics

If you need to backfill DailySummary rows (e.g. after importing historical data):

```bash
python manage.py rebuild_daily_summaries
```

### Sending scheduled reports (manually)

```bash
python manage.py send_scheduled_reports
```

### Django shell with auto-imports

```bash
python manage.py shell_plus  # requires django-extensions
```

### Common debugging queries

```python
# In shell_plus:

# Check a user's store scoping
from apps.accounts.models import User
u = User.objects.get(username='hamisi')
print(u.store, u.role)

# Check DailySummary for today
from apps.analytics.models import DailySummary
from django.utils import timezone
DailySummary.objects.filter(date=timezone.now().date())

# Manually rebuild today's summary
from apps.analytics.services import rebuild_daily_summary
from apps.accounts.models import Store
store = Store.objects.first()
rebuild_daily_summary(store, timezone.now().date())

# Check AI credit balance
from apps.accounts.models import AICredit
AICredit.get_or_create_current(store.organisation)
```

### Checking for N+1 queries

```python
# In settings/development.py — add this:
LOGGING = {
    "version": 1,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"django.db.backends": {"handlers": ["console"], "level": "DEBUG"}},
}
```

This prints every SQL query to the console. Use `select_related()` and `prefetch_related()` to fix N+1 patterns.
