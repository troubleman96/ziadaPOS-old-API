# Expenses App

Tracks all business expenses across stores: rent, salaries, utilities, supplies, transport, marketing, maintenance, and more.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/expenses/` | Paginated list. Supports `search`, `category`, `payment_method`, `ordering`. |
| POST | `/api/v1/expenses/` | Record a new expense. |
| GET | `/api/v1/expenses/{id}/` | Expense detail. |
| PATCH | `/api/v1/expenses/{id}/` | Partial update. |
| DELETE | `/api/v1/expenses/{id}/` | Delete expense. |
| GET | `/api/v1/expenses/summary/` | Aggregated by category/method. |

## Model

- title, category, amount, payment_method, payment_reference
- notes, receipt_url
- recorded_by (User, SET_NULL), store (CASCADE)
- BaseModel: id (UUID), created_at, updated_at
