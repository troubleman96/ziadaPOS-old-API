"""
apps/customers/apps.py

AppConfig for the customers app.
Customers are registered users of the store (not just cashiers/managers).
They can be tagged by segment (VIP, Regular, Occasional, New) and tracked
for total spend, last visit, and open credit balance.
"""

from django.apps import AppConfig


class CustomersConfig(AppConfig):
    """Configuration for the customers Django app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.customers"
    verbose_name = "Customers"
