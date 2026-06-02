# Accounts — Database Schema

## Tables

### `accounts_organisation`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | auto-generated |
| name | varchar(200) | "Duka Kuu" |
| legal_name | varchar(300) | |
| tin | varchar(50) | TRA Tax ID for receipts |
| country | varchar(2) | "TZ" |
| currency | varchar(3) | "TZS" |
| plan | varchar(20) | free / pro / enterprise |
| ai_credits_monthly | int | default 5000 |
| trial_ends_at | datetime | nullable |
| created_at | datetime | |
| updated_at | datetime | |

### `accounts_store`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| organisation_id | FK → organisation | CASCADE |
| name | varchar(200) | "Kariakoo" |
| code | varchar(10) | short code |
| address | text | |
| area | varchar(100) | "Kariakoo" |
| phone | varchar(30) | |
| till_count | smallint | default 1 |
| is_active | bool | default true |
| created_at | datetime | |
| updated_at | datetime | |

**Unique:** `(organisation_id, name)`

### `accounts_user`
| Column | Type | Notes |
|--------|------|-------|
| id | bigint PK | Django default |
| username | varchar(150) | unique |
| email | varchar(254) | |
| first_name | varchar(150) | |
| last_name | varchar(150) | |
| password | varchar(128) | hashed |
| role | varchar(20) | admin / manager / cashier |
| store_id | FK → store | nullable, SET NULL |
| phone | varchar(30) | |
| avatar_hue | smallint | 0–360 |
| is_active | bool | |
| date_joined | datetime | |
| created_at | datetime | |
| updated_at | datetime | |

### `accounts_aicredit`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| organisation_id | FK → organisation | CASCADE |
| year | smallint | e.g. 2026 |
| month | smallint | 1–12 |
| used | int | default 0 |
| allocated | int | default 5000 |
| created_at | datetime | |
| updated_at | datetime | |

**Unique:** `(organisation_id, year, month)`
