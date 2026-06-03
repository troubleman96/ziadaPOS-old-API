"""
Management command: seed_plans

Creates the three default subscription plans if they don't already exist.
Safe to run repeatedly — uses update_or_create so re-running never duplicates.

Usage:
    python manage.py seed_plans
"""

from django.core.management.base import BaseCommand

from apps.subscriptions.models import SubscriptionPlan

PLANS = [
    {
        "slug": "monthly",
        "name": "Monthly",
        "description": "Month-to-month plan. Cancel anytime.",
        "price_per_month": 25_000,
        "duration_months": 1,
        "included_stores": 3,
        "extra_store_price_per_month": 12_000,
        "is_active": True,
        "sort_order": 1,
    },
    {
        "slug": "half-yearly",
        "name": "6-Month Package",
        "description": "Save 8% — pay for 6 months upfront at 23,000 TZS/month.",
        "price_per_month": 23_000,
        "duration_months": 6,
        "included_stores": 3,
        "extra_store_price_per_month": 12_000,
        "is_active": True,
        "sort_order": 2,
    },
    {
        "slug": "yearly",
        "name": "Yearly Package",
        "description": "Best value — pay for 12 months at 22,000 TZS/month. Save 12%.",
        "price_per_month": 22_000,
        "duration_months": 12,
        "included_stores": 3,
        "extra_store_price_per_month": 12_000,
        "is_active": True,
        "sort_order": 3,
    },
]


class Command(BaseCommand):
    help = "Seed the three default subscription plans (idempotent)."

    def handle(self, *args, **options):
        created_count = 0
        for plan_data in PLANS:
            slug = plan_data.pop("slug")
            _, created = SubscriptionPlan.objects.update_or_create(
                slug=slug,
                defaults=plan_data,
            )
            plan_data["slug"] = slug  # restore for any re-use
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"  Created plan: {plan_data['name']}"))
            else:
                self.stdout.write(f"  Plan already exists (updated): {plan_data['name']}")

        if created_count:
            self.stdout.write(self.style.SUCCESS(f"\n✓ {created_count} plan(s) created."))
        else:
            self.stdout.write(self.style.SUCCESS("\n✓ All plans already up to date."))
