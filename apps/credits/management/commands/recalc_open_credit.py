"""
Management command: recalc_open_credit

Recalculates and saves Customer.open_credit for all customers who have
CreditTab records. Run once after deploying the fix that adds
open_credit updates to _process_sale.

Usage:
    python manage.py recalc_open_credit
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum

from apps.credits.models import CreditTab
from apps.customers.models import Customer


class Command(BaseCommand):
    help = "Recalculate Customer.open_credit from open CreditTabs."

    def handle(self, *args, **options):
        customers = Customer.objects.filter(credit_tabs__isnull=False).distinct()
        updated = 0

        for customer in customers:
            result = CreditTab.objects.filter(
                customer=customer,
                status__in=[CreditTab.STATUS_OPEN, CreditTab.STATUS_PARTIAL],
            ).aggregate(total_amount=Sum("amount"), total_paid=Sum("amount_paid"))

            total_amount = result["total_amount"] or 0
            total_paid   = result["total_paid"]   or 0
            correct_balance = max(0, total_amount - total_paid)

            if customer.open_credit != correct_balance:
                customer.open_credit = correct_balance
                customer.save(update_fields=["open_credit", "updated_at"])
                self.stdout.write(
                    f"  {customer.name}: set open_credit = TZS {correct_balance:,}"
                )
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Updated {updated} customer(s)."
        ))
