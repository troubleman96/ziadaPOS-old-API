"""
Management command: seed_global_categories

Creates ~200 pre-seeded global product categories covering every common Tanzania
POS vertical: retail duka, wholesale, pharmacy, restaurant, hardware, salon,
electronics, clothing, stationery, agriculture, and more.

Safe to run repeatedly — uses update_or_create so re-running never duplicates.

Usage:
    python manage.py seed_global_categories
"""

from django.core.management.base import BaseCommand

from apps.inventory.models import Category

# (name, sort_order)  — sort_order groups categories by sector
GLOBAL_CATEGORIES = [
    # ── Grocery & Staples ──────────────────────────────────────────────
    ("Grocery",                       10),
    ("Rice & Cereals",                11),
    ("Flour & Maize Products",        12),
    ("Cooking Oil",                   13),
    ("Sugar & Salt",                  14),
    ("Pulses & Legumes",              15),
    ("Pasta & Noodles",               16),
    ("Canned & Packaged Foods",       17),
    ("Bread & Baked Goods",           18),
    ("Dairy Products",                19),
    ("Eggs",                          20),
    ("Frozen Foods",                  21),
    ("Fresh Meat",                    22),
    ("Fresh Fish & Seafood",          23),
    ("Fresh Vegetables",              24),
    ("Fresh Fruits",                  25),
    ("Herbs & Spices",                26),
    ("Condiments & Sauces",           27),
    ("Tea & Coffee",                  28),
    ("Porridge & Uji",                29),
    ("Cooking Ingredients",           30),
    ("Dried Fish (Dagaa)",            31),
    ("Coconut Products",              32),
    ("Groundnuts & Peanut Products",  33),
    ("Honey & Spreads",               34),

    # ── Beverages ─────────────────────────────────────────────────────
    ("Soft Drinks",                   40),
    ("Juices",                        41),
    ("Water & Mineral Water",         42),
    ("Energy Drinks",                 43),
    ("Beer",                          44),
    ("Wine & Spirits",                45),
    ("Milk & Dairy Drinks",           46),
    ("Traditional Drinks",            47),
    ("Squash & Cordials",             48),
    ("Hot Drinks",                    49),

    # ── Household ─────────────────────────────────────────────────────
    ("Household Items",               60),
    ("Cleaning Supplies",             61),
    ("Detergents & Washing Powder",   62),
    ("Dishwashing Products",          63),
    ("Floor & Surface Cleaners",      64),
    ("Toilet & Bathroom Products",    65),
    ("Disinfectants",                 66),
    ("Pest Control",                  67),
    ("Candles & Matches",             68),
    ("Air Fresheners",                69),
    ("Plasticware & Containers",      70),
    ("Kitchenware & Utensils",        71),
    ("Bedding & Linens",              72),
    ("Buckets & Basins",              73),
    ("Charcoal & Firewood",           74),
    ("Cookers & Stoves",              75),

    # ── Personal Care ─────────────────────────────────────────────────
    ("Personal Care",                 90),
    ("Soap & Body Wash",              91),
    ("Shampoo & Conditioner",         92),
    ("Hair Products",                 93),
    ("Deodorant & Perfume",           94),
    ("Oral Care",                     95),
    ("Skin Care & Moisturizers",      96),
    ("Sanitary Products",             97),
    ("Men's Grooming",                98),
    ("Razors & Shaving",              99),
    ("Cotton Wool & Pads",           100),
    ("Sunscreen & Tanning",          101),

    # ── Baby & Infant ─────────────────────────────────────────────────
    ("Baby Products",                110),
    ("Diapers & Nappies",            111),
    ("Baby Food & Formula",          112),
    ("Baby Care Products",           113),
    ("Baby Clothing",                114),
    ("Baby Accessories",             115),

    # ── Pharmacy & Health ─────────────────────────────────────────────
    ("Prescription Drugs",           130),
    ("OTC Medications",              131),
    ("Antibiotics",                  132),
    ("Pain Relief & Analgesics",     133),
    ("Antimalarials",                134),
    ("Antiparasitic Drugs",          135),
    ("Antifungals",                  136),
    ("Antihistamines",               137),
    ("Antacids & Digestive",         138),
    ("Cough & Cold Remedies",        139),
    ("Eye & Ear Drops",              140),
    ("Vitamins & Supplements",       141),
    ("Multivitamins",                142),
    ("Iron & Folate",                143),
    ("Vitamin C & D",                144),
    ("Zinc Supplements",             145),
    ("Herbal Medicine",              146),
    ("Traditional Remedies",         147),
    ("Medical Supplies",             148),
    ("Syringes & Needles",           149),
    ("Gloves & Protective Equipment",150),
    ("Bandages & Wound Care",        151),
    ("Cotton & Gauze",               152),
    ("First Aid Kits",               153),
    ("Thermometers",                 154),
    ("Blood Pressure Monitors",      155),
    ("Blood Glucose Monitors",       156),
    ("Contraceptives",               157),
    ("Oral Rehydration Salts",       158),

    # ── Restaurant & Food Service ─────────────────────────────────────
    ("Food Ingredients (Bulk)",      170),
    ("Meat & Poultry (Bulk)",        171),
    ("Fish & Seafood (Bulk)",        172),
    ("Vegetables (Bulk)",            173),
    ("Fruits (Bulk)",                174),
    ("Spices & Seasonings (Bulk)",   175),
    ("Cooking Oils & Fats (Bulk)",   176),
    ("Sauces & Marinades",           177),
    ("Bakery Ingredients",           178),
    ("Packaging & Containers",       179),
    ("Disposable Cutlery & Cups",    180),
    ("Napkins & Tissues",            181),

    # ── Hardware & Construction ───────────────────────────────────────
    ("Hand Tools",                   200),
    ("Power Tools",                  201),
    ("Plumbing Supplies",            202),
    ("Pipes & Fittings",             203),
    ("Electrical Supplies",          204),
    ("Cables & Wiring",              205),
    ("Switches & Sockets",           206),
    ("Bulbs & Lighting",             207),
    ("Paint & Coatings",             208),
    ("Tiles & Flooring",             209),
    ("Roofing Materials",            210),
    ("Cement & Concrete",            211),
    ("Sand & Aggregates",            212),
    ("Timber & Wood",                213),
    ("Nails, Screws & Bolts",        214),
    ("Locks & Security Hardware",    215),
    ("Safety Equipment",             216),
    ("Adhesives & Sealants",         217),
    ("Garden & Outdoor",             218),
    ("Irrigation Supplies",          219),
    ("Fencing & Gates",              220),
    ("Building Materials",           221),
    ("Welding Supplies",             222),
    ("Tape & Fasteners",             223),

    # ── Electronics ──────────────────────────────────────────────────
    ("Mobile Phones",                240),
    ("Phone Cases & Covers",         241),
    ("Screen Protectors",            242),
    ("Chargers & Cables",            243),
    ("Earphones & Headphones",       244),
    ("Power Banks",                  245),
    ("Computers & Laptops",          246),
    ("Computer Accessories",         247),
    ("Keyboards & Mice",             248),
    ("Printers & Scanners",          249),
    ("TVs & Displays",               250),
    ("Audio & Speakers",             251),
    ("Smart Watches & Wearables",    252),
    ("Cameras & Accessories",        253),
    ("CCTV & Security Systems",      254),
    ("Networking & WiFi",            255),
    ("USB Drives & Storage",         256),
    ("Batteries",                    257),
    ("Smart Home Devices",           258),
    ("Solar & Power Solutions",      259),
    ("Inverters & UPS",              260),

    # ── Clothing & Fashion ────────────────────────────────────────────
    ("Men's Clothing",               280),
    ("Women's Clothing",             281),
    ("Children's Clothing",          282),
    ("Infant Clothing",              283),
    ("Men's Shoes",                  284),
    ("Women's Shoes",                285),
    ("Children's Shoes",             286),
    ("Bags & Handbags",              287),
    ("Belts & Wallets",              288),
    ("Sunglasses",                   289),
    ("Jewelry & Accessories",        290),
    ("Sportswear & Activewear",      291),
    ("Traditional Attire",           292),
    ("Kanga & Vitenge",              293),
    ("School Uniforms",              294),
    ("Work & Industrial Uniforms",   295),
    ("Underwear & Socks",            296),
    ("Hats & Caps",                  297),
    ("Scarves & Hijabs",             298),
    ("Fabrics & Textiles",           299),

    # ── Salon & Beauty ────────────────────────────────────────────────
    ("Salon Hair Products",          320),
    ("Hair Color & Bleach",          321),
    ("Hair Extensions & Wigs",       322),
    ("Hair Relaxers & Treatments",   323),
    ("Braiding & Weave Products",    324),
    ("Salon Skin Care",              325),
    ("Facial Cleansers & Toners",    326),
    ("Makeup & Cosmetics",           327),
    ("Lipstick & Lip Gloss",         328),
    ("Foundation & Concealer",       329),
    ("Eyebrow & Eyeliner Products",  330),
    ("Nail Care & Polish",           331),
    ("Nail Extensions & Gel",        332),
    ("Salon Equipment & Tools",      333),
    ("Combs, Brushes & Accessories", 334),
    ("Body Lotion & Oils",           335),

    # ── Stationery & School ───────────────────────────────────────────
    ("Exercise Books & Notebooks",   350),
    ("Pens & Pencils",               351),
    ("Rulers & Geometry Sets",       352),
    ("Office Supplies",              353),
    ("Printing Paper",               354),
    ("Ink & Toner Cartridges",       355),
    ("School Bags & Backpacks",      356),
    ("Art & Drawing Supplies",       357),
    ("Filing & Storage Products",    358),
    ("Stamps & Ink Pads",            359),
    ("Calculators",                  360),
    ("Whiteboards & Markers",        361),

    # ── Agriculture & Farming ─────────────────────────────────────────
    ("Seeds & Seedlings",            380),
    ("Fertilizers",                  381),
    ("Pesticides & Herbicides",      382),
    ("Irrigation Equipment",         383),
    ("Farm Tools & Equipment",       384),
    ("Animal Feed",                  385),
    ("Veterinary Products",          386),
    ("Greenhouse Supplies",          387),
    ("Soil Amendments",              388),
    ("Harvesting Bags & Sacks",      389),

    # ── Wholesale & Industrial ────────────────────────────────────────
    ("Bulk Packaging Materials",     400),
    ("Plastic Bags & Wrapping",      401),
    ("Boxes & Cartons",              402),
    ("Industrial Cleaning Supplies", 403),
    ("Industrial Tools & Equipment", 404),
    ("Safety Gear & PPE",            405),
    ("Lubricants & Oils",            406),
    ("Automotive Parts",             407),
    ("Tyres & Accessories",          408),
    ("Furniture & Office Equipment", 409),
    ("Printing & Branding Supplies", 410),
    ("Weighing Scales & Equipment",  411),

    # ── Miscellaneous / Catch-all ─────────────────────────────────────
    ("Toys & Games",                 430),
    ("Sports Equipment",             431),
    ("Pet Products",                 432),
    ("Books & Magazines",            433),
    ("Gifts & Novelties",            434),
    ("Religious Items",              435),
    ("Medical Equipment (Rental)",   436),
    ("Event & Party Supplies",       437),
    ("Recycled & Eco Products",      438),
    ("Other",                        999),
]


class Command(BaseCommand):
    help = "Seed ~200 global product categories for Tanzania POS verticals (idempotent)."

    def handle(self, *args, **options):
        created_count  = 0
        updated_count  = 0

        for name, sort_order in GLOBAL_CATEGORIES:
            _, created = Category.objects.update_or_create(
                name=name,
                defaults={"sort_order": sort_order, "is_global": True},
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        total = len(GLOBAL_CATEGORIES)
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ {created_count} created, {updated_count} updated "
                f"({total} total global categories)."
            )
        )
