"""
apps/credits/apps.py

AppConfig for the credits ("madeni") app.

This app manages the credit/debt lifecycle for registered customers:
  - CreditTab    : a credit record created when a sale is made on credit
  - CreditPayment: a partial or full payment against the customer's balance
  - CreditMessage: WhatsApp/call communication log (in and outbound)
  - CreditNote   : internal staff notes on the customer's credit relationship
"""

from django.apps import AppConfig


class CreditsConfig(AppConfig):
    """Configuration for the credits Django app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.credits"
    verbose_name = "Credits (Madeni)"
