# apps/reports — Report Generation, Export History & Scheduled Reports

## What this app does

`apps/reports` provides on-demand and scheduled business report generation for Ziada POS. It supports four report types (Sales Summary, Inventory Valuation, Tax Statement, Credit Aged Debtors), two output formats (CSV file download, JSON data for PDF rendering), an export history audit trail, and a recurring report scheduler.

**UI page this app powers:**
- `/reports` — three-tab page:
  - **Overview tab** — QuickExportCard grid showing the four available report types with a "Generate" button each
  - **History tab** — table of previously generated exports with "Download" links
  - **Scheduled tab** — list of recurring report configurations with enable/disable toggles

---

## Models

### Constants

```python
REPORT_SALES     = "sales"       # Sales Summary
REPORT_INVENTORY = "inventory"   # Inventory Valuation
REPORT_TAX       = "tax"         # Tax Statement
REPORT_CREDIT    = "credit"      # Credit Aged Debtors

FORMAT_CSV  = "csv"    # File download
FORMAT_JSON = "json"   # Structured data (frontend renders as PDF)

FREQ_DAILY   = "daily"
FREQ_WEEKLY  = "weekly"
FREQ_MONTHLY = "monthly"

RANGE_7D    = "7d"     # Last 7 days
RANGE_30D   = "30d"    # Last 30 days
RANGE_90D   = "90d"    # Last 90 days
RANGE_MONTH = "month"  # Current calendar month
RANGE_YTD   = "ytd"    # Year to date
```

---

### `ScheduledReport`

A recurring report configuration. Stores what to generate, how often, and who receives it.

| Field | Type | Description |
|-------|------|-------------|
| `store` | FK → Store (CASCADE) | Store this schedule belongs to. |
| `organisation` | FK → Organisation (CASCADE) | For multi-store scoping. |
| `created_by` | FK → User (nullable, SET_NULL) | Manager who set this up. |
| `report_type` | CharField(20) | `sales` / `inventory` / `tax` / `credit` |
| `name` | CharField(200) | Display name, e.g. "Daily Sales Summary". |
| `frequency` | CharField(10) | `daily` / `weekly` / `monthly` |
| `date_range_preset` | CharField(10) | What period to include: `7d` / `30d` / `90d` / `month` / `ytd` |
| `recipients` | JSONField | List of email strings: `["hamisi@duka.co.tz", "accountant@firm.co.tz"]` |
| `is_enabled` | BooleanField | Toggle — False = paused. Controlled by the toggle switch in the UI. |
| `last_sent_at` | DateTimeField (nullable) | Timestamp of most recent successful delivery. |
| `next_send_at` | DateTimeField (nullable) | When the next auto-send will fire. |

**Computed property:** `recipient_count` — `len(recipients or [])`.

**DB index:** `(store, is_enabled)` — used by the management command to find enabled schedules.

**Note:** The actual email dispatch is handled by `python manage.py send_scheduled_reports` (or a Celery beat task in production). The MVP stores the configuration; the dispatch infrastructure is separate.

---

### `ReportExport`

Audit record for every report that was generated, whether manually or by a schedule.

**Key design decision:** The file content (CSV/PDF bytes) is **NOT stored here.** Only the metadata is stored. Re-downloads regenerate the report from `date_from` and `date_to`. This keeps the database lean and ensures downloads reflect any data corrections made since the original generation.

| Field | Type | Description |
|-------|------|-------------|
| `store` | FK → Store (CASCADE) | Which store's data was exported. |
| `organisation` | FK → Organisation (CASCADE) | Multi-store scoping. |
| `created_by` | FK → User (nullable, SET_NULL) | User who clicked "Generate" (null for scheduled exports). |
| `report_type` | CharField(20) | `sales` / `inventory` / `tax` / `credit` |
| `name` | CharField(200) | Display name, e.g. "Sales Summary". |
| `period_label` | CharField(100) | Human-readable period: `"1 – 24 May 2026"`, `"April 2026"`. Shown in the History table. |
| `date_from` | DateField | Start date of the report (stored for re-download). |
| `date_to` | DateField | End date of the report (stored for re-download). |
| `format` | CharField(10) | `csv` or `json` |
| `file_size_bytes` | PositiveIntegerField | Approximate size in bytes (calculated at generation time, for UI display). |
| `scheduled_report` | FK → ScheduledReport (nullable, SET_NULL) | Which schedule triggered this (null = manual). |

**Computed properties:**

```python
export.file_size_display  # str: "284 KB", "1.2 MB"
export.is_manual          # bool: scheduled_report_id is None
```

**DB indexes:** `(store, report_type)`, `(store, created_at)`.

---

## Services (`services.py`)

### `get_report_data(report_type, store, start, end) → dict`

Central dispatcher. Routes to the appropriate generator based on `report_type`.

```python
"sales"     → generate_sales_summary(store, start, end)
"inventory" → generate_inventory_valuation(store)       # ignores dates — always current
"tax"       → generate_tax_statement(store, start, end)
"credit"    → generate_credit_aged_debtors(store)       # ignores dates — always current
```

---

### `generate_sales_summary(store, start, end) → dict`

Comprehensive sales report for a date range.

```python
{
  "kpis": {
    "total_revenue": 4850000,
    "total_profit": 820000,
    "margin_pct": 16.9,
    "transaction_count": 87,
    "avg_ticket": 55747,
    "tax_collected": 630000,
  },
  "daily_trend": [
    {"date": "2026-05-01", "revenue": 180000, "transactions": 8},
    ...
  ],
  "top_products": [
    {"name": "Unga wa Sembe 10kg", "units_sold": 42, "revenue": 1197000},
    ...
  ],
  "payment_mix": [
    {"method": "M-Pesa", "amount": 2300000, "pct": 47.4},
    ...
  ],
  "category_breakdown": [...],
  "day_of_week": [...],
}
```

---

### `generate_inventory_valuation(store) → dict`

Current stock values using product prices (not transaction snapshots). Always as-of-today regardless of date range.

```python
{
  "products": [
    {
      "name": "Unga wa Sembe 10kg",
      "sku": "UWS-10",
      "category": "Grocery",
      "stock": 50,
      "cost": 22000,
      "price": 28500,
      "cost_value": 1100000,   # stock × cost
      "retail_value": 1425000, # stock × price
    },
    ...
  ],
  "category_subtotals": [...],
  "totals": {
    "total_cost_value": 45000000,
    "total_retail_value": 60000000,
    "total_units": 1847,
  },
  "valuation_date": "2026-05-26",
}
```

---

### `generate_tax_statement(store, start, end) → dict`

VAT/TRA-ready tax report covering paid transactions only (credit transactions excluded until cash-settled).

```python
{
  "vat_rate": 0.18,
  "summary": {
    "taxable_revenue": 4114407,
    "vat_collected": 630000,
    "total_revenue": 4850000,
    "transaction_count": 87,
  },
  "daily": [
    {"date": "2026-05-01", "taxable_revenue": 152542, "vat": 27458, "gross": 180000},
    ...
  ],
  "note": "Credit sales are excluded until payment is received.",
}
```

---

### `generate_credit_aged_debtors(store) → dict`

Accounts receivable report, always current (ignores date range). Groups customers with open credit into aging buckets.

```python
{
  "customers": [
    {
      "name": "Fatuma Ally",
      "phone": "+255712345678",
      "open_credit": 150000,
      "bucket": "8–30 days",
      "oldest_tab_date": "2026-04-28",
    },
    ...
  ],
  "aging_summary": {
    "current": 200000,
    "1_7d": 80000,
    "8_30d": 350000,
    "31_60d": 200000,
    "60plus": 100000,
  },
  "totals": {
    "total_outstanding": 930000,
    "customer_count": 12,
  },
  "as_of_date": "2026-05-26",
}
```

Aging buckets follow the same logic as `apps/credits/api/views.py`:
- **Current** — tab not yet due or no due date
- **1–7 days** — 1 to 7 days overdue
- **8–30 days** — 8 to 30 days overdue
- **31–60 days** — 31 to 60 days overdue
- **60+ days** — more than 60 days overdue

---

### `build_csv(report_type, data) → tuple[str, str]`

Converts a report data dict into a CSV string and generates a filename.

Returns `(csv_string, filename)` where:
- `csv_string` — UTF-8 encoded CSV text (uses Python's `csv` module)
- `filename` — e.g. `"sales-summary-2026-05.csv"`, `"inventory-valuation-2026-05-26.csv"`

Each report type has a custom CSV layout. For example, the Sales Summary CSV has separate sections (KPIs, Daily Trend, Top Products, Payment Mix) separated by blank rows.

---

### `parse_range_for_report(validated_data) → tuple[date, date, str]`

Resolves the date range from serializer validated data. Handles both preset ranges (`?range=30d`) and explicit dates (`date_from` + `date_to`).

Returns `(start_date, end_date, period_label)` where `period_label` is a human-readable string:
- `"7d"` → `"19–26 May 2026"`
- `"month"` → `"April 2026"` (last full calendar month)
- `"ytd"` → `"1 Jan – 26 May 2026"`
- Explicit dates → `"1–24 May 2026"`

---

### `compute_next_send(frequency, from_dt) → datetime`

Calculates the next scheduled delivery datetime:
- `"daily"` → `from_dt + 1 day`
- `"weekly"` → `from_dt + 7 days`
- `"monthly"` → first day of next calendar month

---

## API Endpoints

All routes mount at `/api/v1/reports/`.

### `GET /types/`

**View:** `ReportTypesView`
**Auth:** `IsAuthenticated`

Returns the static catalogue of available report types with metadata for the Overview tab's QuickExportCard grid.

```json
{
  "report_types": [
    {
      "id": "sales",
      "name": "Sales Summary",
      "desc": "Daily sales totals, top products, payment breakdown...",
      "color": "accent",
      "supports_date_range": true
    },
    {
      "id": "inventory",
      "name": "Inventory Valuation",
      "desc": "Cost and retail value of all stock on hand...",
      "color": "good",
      "supports_date_range": false
    },
    ...
  ]
}
```

`supports_date_range: false` tells the UI to hide the date picker for that report type.

---

### `POST /generate/`

**View:** `GenerateReportView`
**Auth:** `IsAuthenticated`

Generates a report and returns it as CSV file download or JSON data.

**Request body:**
```json
{
  "report_type": "sales",
  "format": "csv",
  "range": "30d"
}
```

Or with explicit dates:
```json
{
  "report_type": "tax",
  "format": "json",
  "date_from": "2026-05-01",
  "date_to": "2026-05-24"
}
```

**CSV response:**
```
HTTP 200
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="sales-summary-2026-05.csv"

[CSV content]
```

This triggers a browser file download. The Content-Disposition header instructs the browser to save the file rather than display it.

**JSON response:**
```json
{
  "report_type": "sales",
  "period_label": "1 – 24 May 2026",
  "date_from": "2026-05-01",
  "date_to": "2026-05-24",
  "report": { ...report data dict... }
}
```

**Side effect:** A `ReportExport` audit record is created in both cases, with `file_size_bytes` set to the byte length of the generated content.

---

### `GET /exports/`

**View:** `ExportListView`
**Auth:** `IsAuthenticated`

Returns export history for the user's store (newest first).

**Query params:**
- `?report_type=sales` — filter by report type
- `?format=csv` — filter by format
- `?limit=50` — max records to return (default 50, max 200)

---

### `GET /exports/{export_id}/download/`

**View:** `ExportDownloadView`
**Auth:** `IsAuthenticated`

Re-generates and streams the export. The report data is regenerated from the stored `date_from` / `date_to` — it is NOT retrieved from a stored file. This means:
- Downloads always reflect any data corrections made since original export
- No large BLOBs in the database

Returns CSV (with Content-Disposition header) for CSV-format exports, JSON data for JSON-format exports.

---

### `GET /scheduled/`

**View:** `ScheduledReportListCreateView`
**Auth:** `IsAuthenticated`

Lists all scheduled reports for the user's store.

```json
{
  "scheduled_reports": [...],
  "total": 3,
  "active_count": 2
}
```

---

### `POST /scheduled/`

**Auth:** `IsAuthenticated`, manager/owner/admin role (checked inline)

Creates a new scheduled report.

```json
{
  "report_type": "sales",
  "name": "Weekly Sales Summary",
  "frequency": "weekly",
  "date_range_preset": "7d",
  "recipients": ["hamisi@dukakuu.co.tz", "finance@example.com"]
}
```

Returns 201. `next_send_at` is automatically computed via `compute_next_send()`.

---

### `PATCH /scheduled/{id}/`

**Auth:** Manager/owner/admin

Update a scheduled report. Used for:
- **Toggle:** `{ "is_enabled": false }` — pause/resume
- **Edit:** `{ "name": "...", "frequency": "monthly", "recipients": [...] }`

---

### `DELETE /scheduled/{id}/`

**Auth:** Manager/owner/admin

Deletes the scheduled report configuration. Existing `ReportExport` records created by this schedule remain (FK is `SET_NULL`).

---

## Design Decisions

**Why not store the file content in the database?**
Storing CSV/PDF bytes as DB BLOBs has two problems: (1) it bloats the database significantly — a monthly inventory report for a 500-product store is ~50KB, and with frequent scheduled reports this adds up; (2) stored files become stale — if a transaction is corrected after the report was generated, the stored file shows wrong data. Regenerating on demand is simpler, always accurate, and keeps the DB lean.

**Why `recipients` as a JSONField instead of a separate `Recipient` table?**
The recipients list is small (1-5 emails), rarely changes, and is always used as a whole (we send to all of them or none). A separate table would add a JOIN with no benefit. JSON array on the model is the simplest representation for MVP.

**Why does the `credit` report ignore the date range?**
The Credit Aged Debtors report answers "who owes us money right now?" — it's always a point-in-time snapshot of the current outstanding balance. There's no meaningful "credit report for May" — you want to know what's outstanding today, not what was outstanding 30 days ago.

**Why `FORMAT_JSON` instead of `FORMAT_PDF`?**
PDFs require a headless browser or a PDF library (WeasyPrint, ReportLab, etc.) and server-side rendering. For MVP, the JSON format returns the structured report data and the frontend renders it into a print-ready view. This keeps the backend simple and allows the frontend to control the PDF layout.

---

## Common Gotchas

1. **`generate_inventory_valuation` uses current product prices, not transaction snapshots.** The inventory value is always computed from `product.price × product.stock`. If prices were recently updated, the report reflects the new prices — not what was paid historically.

2. **`parse_range_for_report` returns today as `date_to` for all presets.** If a report is generated at 09:00, `date_to = today`. If regenerated via the download endpoint at 17:00, `date_to` is still the same stored date. This is correct — the download endpoint uses the stored `date_from`/`date_to`, not today.

3. **The `month` range preset returns the last completed calendar month**, not the current month. If today is May 26, `?range=month` returns April 1–30. This is intentional for the Tax Statement use case — tax returns are filed for completed months.

4. **CSV Content-Disposition triggers browser download.** If you're testing the `POST /generate/?format=csv` endpoint via an API client (Postman, curl), save the response body to a file. The `Content-Disposition: attachment` header is only meaningful to browsers.

5. **Scheduled report dispatch is not implemented in the API server.** The `ScheduledReport` model and `next_send_at` field exist, but the actual email sending requires `python manage.py send_scheduled_reports` or a Celery beat job. In the MVP, the UI shows scheduled reports as configurations but they are not auto-sent unless the management command is wired up.
