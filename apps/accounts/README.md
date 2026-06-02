# apps/accounts — Users, Organisations & Stores

`apps/accounts` is the identity and access layer for Ziada. It owns the data
models that answer "who is this user, which organisation do they belong to,
which store do they work in, and what are they allowed to do?"

Every other app imports from this one (`ForeignKey` to `Store`, `User`, or
`Organisation`). Nothing in `accounts` imports from other feature apps —
it sits at the base of the dependency graph.

---

## Where it fits

```
accounts (this app)
  ├── owns: Organisation, Store, User, AICredit
  └── imported by: all other apps (inventory, transactions, credits, customers,
                   analytics, ai, reports)
```

---

## Data Models

### Organisation

The top-level tenant entity. Represents a business (e.g. "Duka Kuu").

| Field | Type | Notes |
|-------|------|-------|
| `name` | CharField(200) | Trading name, shown in sidenav header |
| `legal_name` | CharField(300, blank) | Full registered name |
| `tin` | CharField(50, blank) | Tanzania TRA Tax ID, printed on receipts |
| `country` | CharField(2) | ISO country code, default "TZ" |
| `currency` | CharField(3) | ISO currency code, default "TZS" |
| `ai_credits_monthly` | PositiveIntegerField | Credits allocated per month, default 5000 |
| `plan` | CharField | "free" / "pro" / "enterprise" |
| `trial_ends_at` | DateTimeField(null) | Trial expiry (null = not on trial) |

One organisation → many stores → many users. All data in Ziada is scoped to
a store, and every store belongs to one organisation.

### Store

A physical location owned by an Organisation.

| Field | Type | Notes |
|-------|------|-------|
| `organisation` | FK(Organisation) | CASCADE delete |
| `name` | CharField(200) | "Main Store" or "Branch 2" |
| `code` | CharField(10, blank) | Short code for transaction IDs, e.g. "KRC" |
| `address` | TextField(blank) | Full address |
| `area` | CharField(100, blank) | Neighbourhood, shown in sidenav ("Kariakoo") |
| `phone` | CharField(30, blank) | Contact phone |
| `till_count` | PositiveSmallIntegerField | Number of POS tills, default 1 |
| `is_active` | BooleanField | Inactive stores hidden from store switcher |

**`unique_together = [("organisation", "name")]`** — two stores in the same
organisation cannot share a name.

**`display_name` property** — returns `"Duka Kuu — Kariakoo"` (concatenation of
org name and store name). Used in receipts and page titles.

### User

Custom auth user that extends Django's `AbstractUser`.

**Why custom?** Django's built-in User has username/password/email. We need
`role` (permission level), `store` (which store they work at), `phone` (for
WhatsApp), and `avatar_hue` (for the procedural avatar colour in the UI).

| Field | Type | Notes |
|-------|------|-------|
| `id` | AutoField (PK) | **Note: integer, NOT UUID** (AbstractUser conflict) |
| `role` | CharField | "admin" / "manager" / "cashier" |
| `store` | FK(Store, null) | Their primary store assignment |
| `phone` | CharField(30, blank) | Phone number |
| `avatar_hue` | PositiveSmallIntegerField | 0–360 hue for avatar colour, default 260 |
| `created_at` | DateTimeField(auto_now_add) | From BaseModel |
| `updated_at` | DateTimeField(auto_now) | From BaseModel |

Plus everything from Django's `AbstractUser`: `username`, `password`,
`first_name`, `last_name`, `email`, `is_staff`, `is_active`, `date_joined`.

**⚠️ User.id is an AutoField (integer), not UUID.**
This is the one exception in the system. `AbstractUser` requires control of the
primary key. `BaseModel` normally provides a UUID `id`, but we override it back
to `AutoField` to avoid a PK conflict. The `created_at`/`updated_at` timestamps
still come from BaseModel.

**`role` choices:**
- `admin` — organisation owner, full access to everything
- `manager` — can create/edit products, view analytics, manage staff
- `cashier` — can only use POS, view inventory, manage credits

**`full_name` property** — `get_full_name()` or falls back to `username`.

**`initials` property** — takes first character of first and last name for
the avatar badge ("Hamisi Mwakapaga" → "HM"). Falls back to first two chars
of username.

**`AUTH_USER_MODEL = "accounts.User"` in settings** — must be set before the
first migration. Changing it after migrations exist requires a full DB reset.

### AICredit

Tracks monthly AI credit consumption per organisation. One record per
organisation per calendar month.

| Field | Type | Notes |
|-------|------|-------|
| `organisation` | FK(Organisation, CASCADE) | Which org |
| `year` | PositiveSmallIntegerField | e.g. 2026 |
| `month` | PositiveSmallIntegerField | 1–12 |
| `used` | PositiveIntegerField | Credits consumed, starts at 0 |
| `allocated` | PositiveIntegerField | Copied from org.ai_credits_monthly |

**`unique_together = [("organisation", "year", "month")]`** — one row per org per month.

**`remaining` property** — `max(0, allocated - used)`.

**`get_or_create_current(organisation)` classmethod** — called by `apps/ai/service.py`
before every AI API call. Gets the current month's record, or creates it if this is
the first request of the month.

---

## API Endpoints

All mounted at `/api/v1/accounts/`. Authentication required (JWT Bearer).

### Authentication (at `/api/v1/auth/`)

These come from `djangorestframework-simplejwt`:

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/api/v1/auth/login/` | Login → `{access, refresh}` tokens |
| POST | `/api/v1/auth/refresh/` | Exchange refresh for new access token |
| POST | `/api/v1/auth/verify/` | Check if access token is valid |

**Login request:**
```json
{ "username": "hamisi", "password": "secret" }
```
**Login response:**
```json
{ "access": "eyJ...", "refresh": "eyJ..." }
```
All subsequent requests include: `Authorization: Bearer eyJ...`

Access tokens expire in 60 minutes (configurable via `JWT_ACCESS_TOKEN_LIFETIME_MINUTES`).
Refresh tokens expire in 7 days (`JWT_REFRESH_TOKEN_LIFETIME_DAYS`).

When a refresh token is used, a new one is issued (rotating refresh tokens,
controlled by `ROTATE_REFRESH_TOKENS = True`). The old refresh token is
blacklisted (`BLACKLIST_AFTER_ROTATION = True`).

### Current User Profile

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/v1/accounts/me/` | Current user profile |
| PATCH | `/api/v1/accounts/me/` | Update name, phone, avatar_hue |
| POST | `/api/v1/accounts/me/change-password/` | Change own password |

**GET /me/ response:**
```json
{
  "id": 1,
  "username": "hamisi",
  "full_name": "Hamisi Mwakapaga",
  "first_name": "Hamisi",
  "last_name": "Mwakapaga",
  "email": "hamisi@dukakuu.co.tz",
  "role": "admin",
  "store": { "id": "uuid", "name": "Main Store", "area": "Kariakoo" },
  "phone": "+255712345678",
  "avatar_hue": 260,
  "initials": "HM"
}
```

**POST /me/change-password/ body:**
```json
{ "old_password": "current", "new_password": "newpass123!" }
```

### Organisation

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/v1/accounts/organisation/` | Get organisation details |

Returns the organisation for the authenticated user's store. Read-only from
the API (admin manages org settings via Django Admin).

### Staff Management

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/v1/accounts/users/` | List all staff (managers and admins only) |
| POST | `/api/v1/accounts/users/` | Create staff member |
| GET | `/api/v1/accounts/users/{id}/` | Get staff member detail |
| PATCH | `/api/v1/accounts/users/{id}/` | Update staff member |
| DELETE | `/api/v1/accounts/users/{id}/` | Deactivate staff member (soft delete) |

Create staff body:
```json
{
  "username": "cashier2",
  "password": "securepass",
  "first_name": "Amina",
  "last_name": "Hassan",
  "role": "cashier",
  "phone": "+255712345679"
}
```

### Stores

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/v1/accounts/stores/` | List all stores in the organisation |
| POST | `/api/v1/accounts/stores/` | Create a new store (admin only) |

---

## Admin

All four models registered in Django Admin at `/admin/`.

`UserAdmin` extends `django.contrib.auth.admin.UserAdmin` to show `role`,
`store`, `phone`, and `avatar_hue` in the user list.

`AICredit` admin shows a usage bar (used/allocated) and colour-codes exhausted
months in red.

---

## Design Decisions

1. **`User.id` is integer, not UUID** — `AbstractUser` requires control of the
   primary key to work with Django's auth subsystem (password reset, permissions,
   sessions). Overriding it with UUID causes conflicts in Django internals.
   Every other model uses UUID; User is the one exception. The user `id` is never
   exposed in public API URLs where enumeration matters.

2. **Store-scoped access** — every feature-level request is scoped to
   `request.user.store`. A cashier at Store A cannot see transactions from Store B
   even if they share an organisation. Managers with `admin` role can access all
   stores via organisation-level queries.

3. **Monthly AICredit records** — one record per org per month means we can report
   "you used 2,418 of your 5,000 May credits" without scanning all AI messages.
   The `get_or_create_current()` classmethod handles the month rollover
   automatically — no cron job required.

4. **No session auth** — `DEFAULT_AUTHENTICATION_CLASSES` is JWT only. No cookies,
   no sessions. This keeps the API stateless and CORS-compatible.

---

## Common Gotchas

- **`User.id` is an integer**. Don't try to parse it as UUID. When you need to
  identify a user in analytics or logs, use `user.username` or `user.id` (int).

- **Changing `AUTH_USER_MODEL` after migrations exist requires a full DB wipe.**
  This is a Django constraint. The setting is locked in on first migration.

- **`User.store` can be null** (admin users who manage multiple stores don't
  have a single `store` FK). Always check `request.user.store` is not None before
  using it. Admin users typically access stores via the organisation relationship.

- **JWT tokens must be refreshed before expiry**. The frontend should call
  `POST /auth/refresh/` when it gets a 401. After rotation, the old refresh token
  is blacklisted — don't reuse it.

- **Password validation** is active (minimum length, common password check, etc.).
  Test users in dev can fail the common-password validator if you use "password123".
  Use `pass123!` or similar in tests.
