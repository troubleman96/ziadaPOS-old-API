"""
apps/accounts/tanzania.py

Tanzania-specific constants and POS pre-configuration data.

Used during registration to automatically seed:
  - Product categories matching the business type
  - Default payment methods available in Tanzania
  - Region selection list

All seeding logic is called inside the atomic registration transaction
(see apps/accounts/api/serializers.py → RegistrationSerializer.create()).
"""

# ── Tanzania administrative regions ───────────────────────────────────────────

TANZANIA_REGIONS = [
    "Arusha",
    "Dar es Salaam",
    "Dodoma",
    "Geita",
    "Iringa",
    "Kagera",
    "Katavi",
    "Kigoma",
    "Kilimanjaro",
    "Lindi",
    "Manyara",
    "Mara",
    "Mbeya",
    "Morogoro",
    "Mtwara",
    "Mwanza",
    "Njombe",
    "Pemba North",
    "Pemba South",
    "Pwani",
    "Rukwa",
    "Ruvuma",
    "Shinyanga",
    "Simiyu",
    "Singida",
    "Songwe",
    "Tabora",
    "Tanga",
    "Unguja North",
    "Unguja South",
    "Unguja West",
]

REGION_CHOICES = [(r, r) for r in TANZANIA_REGIONS]


# ── Business type choices ──────────────────────────────────────────────────────

BUSINESS_PHARMACY  = "pharmacy"
BUSINESS_RETAIL    = "retail"
BUSINESS_WHOLESALE = "wholesale"

BUSINESS_TYPE_CHOICES = [
    (BUSINESS_PHARMACY,  "Pharmacy (Duka la Dawa)"),
    (BUSINESS_RETAIL,    "Retail Shop (Duka la Rejareja)"),
    (BUSINESS_WHOLESALE, "Wholesale (Jumla)"),
]


# ── Pre-configured categories per business type ────────────────────────────────
# Seeded automatically into apps.inventory.Category on registration.

BUSINESS_CATEGORY_PRESETS = {
    BUSINESS_PHARMACY: [
        {"name": "Prescription Drugs",    "sort_order": 1},
        {"name": "OTC Medications",        "sort_order": 2},
        {"name": "Vitamins & Supplements", "sort_order": 3},
        {"name": "Medical Supplies",       "sort_order": 4},
        {"name": "Personal Care",          "sort_order": 5},
        {"name": "Baby Products",          "sort_order": 6},
        {"name": "Surgical Items",         "sort_order": 7},
        {"name": "Herbal Medicine",        "sort_order": 8},
    ],
    BUSINESS_RETAIL: [
        {"name": "Grocery",         "sort_order": 1},
        {"name": "Beverages",       "sort_order": 2},
        {"name": "Household",       "sort_order": 3},
        {"name": "Personal Care",   "sort_order": 4},
        {"name": "Snacks",          "sort_order": 5},
        {"name": "Electronics",     "sort_order": 6},
        {"name": "Clothing",        "sort_order": 7},
        {"name": "Stationery",      "sort_order": 8},
        {"name": "Frozen Foods",    "sort_order": 9},
        {"name": "Cleaning Supplies", "sort_order": 10},
    ],
    BUSINESS_WHOLESALE: [
        {"name": "Food Products",      "sort_order": 1},
        {"name": "Beverages",          "sort_order": 2},
        {"name": "Cleaning Supplies",  "sort_order": 3},
        {"name": "Personal Care",      "sort_order": 4},
        {"name": "Agricultural",       "sort_order": 5},
        {"name": "Industrial Goods",   "sort_order": 6},
        {"name": "Packaging",          "sort_order": 7},
        {"name": "Stationery",         "sort_order": 8},
    ],
}


def seed_categories_for_store(store, business_type):
    """
    Create the pre-configured product categories for a newly registered business.

    Categories are global (no store FK) and deduplicated via ignore_conflicts.
    Called inside the atomic registration transaction.

    Args:
        store: not used directly (kept for API signature clarity)
        business_type: one of BUSINESS_PHARMACY / BUSINESS_RETAIL / BUSINESS_WHOLESALE
    """
    from apps.inventory.models import Category

    presets = BUSINESS_CATEGORY_PRESETS.get(business_type, [])
    categories = [
        Category(
            name=preset["name"],
            sort_order=preset["sort_order"],
        )
        for preset in presets
    ]
    if categories:
        Category.objects.bulk_create(categories, ignore_conflicts=True)
