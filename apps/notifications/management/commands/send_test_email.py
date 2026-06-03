"""
Management command: send_test_email

Send a test email to verify ZohoMail SMTP is correctly configured.

Usage:
    python manage.py send_test_email itslugenge96@gmail.com
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test email to verify SMTP configuration."

    def add_arguments(self, parser):
        parser.add_argument("email", type=str, help="Recipient email address.")

    def handle(self, *args, **options):
        to = options["email"]
        self.stdout.write(f"Sending test email to {to}...")

        from apps.notifications.emails import send_test_email
        ok = send_test_email(to)

        if ok:
            self.stdout.write(self.style.SUCCESS(f"✓ Test email sent successfully to {to}"))
        else:
            raise CommandError(f"Failed to send test email to {to}. Check EMAIL_* settings and SMTP credentials.")
