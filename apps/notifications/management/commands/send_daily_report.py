"""
Management command: send_daily_report

Manually trigger the daily sales report email for all stores.
Can also target a single store by --store <id>.

Usage:
    python manage.py send_daily_report
    python manage.py send_daily_report --store <store-uuid>
    python manage.py send_daily_report --dry-run    (logs what would be sent)
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Send the daily sales report email to store owners."

    def add_arguments(self, parser):
        parser.add_argument("--store", type=str, default=None, help="UUID of a specific store.")
        parser.add_argument("--dry-run", action="store_true", help="Log what would be sent without sending.")

    def handle(self, *args, **options):
        from apps.notifications.emails import send_daily_sales_report

        store_id = options.get("store")
        dry_run  = options.get("dry_run", False)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no emails will be sent."))
            from apps.accounts.models import Store
            qs = Store.objects.filter(is_active=True)
            if store_id:
                qs = qs.filter(id=store_id)
            for st in qs:
                self.stdout.write(f"  Would send to: {st.name}")
            return

        store_obj = None
        if store_id:
            from apps.accounts.models import Store
            try:
                store_obj = Store.objects.get(id=store_id)
            except Store.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"Store {store_id} not found."))
                return

        count = send_daily_sales_report(store=store_obj)

        if count:
            self.stdout.write(self.style.SUCCESS(f"✓ Daily report sent to {count} store(s)."))
        else:
            self.stdout.write(self.style.WARNING("No emails sent — check owner emails are set."))
