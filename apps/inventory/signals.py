"""
apps/inventory/signals.py

Django signals for inventory app.

Current signals:
  - post_save on Product → log an OPENING stock adjustment when a new
    product is created with initial stock > 0
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Product, StockAdjustment

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Product)
def create_opening_stock_adjustment(sender, instance, created, **kwargs):
    """
    When a new Product is created with initial stock > 0, automatically
    create an OPENING stock adjustment record so the audit log starts clean.

    This only fires on creation (created=True), not on updates.
    """
    if created and instance.stock > 0:
        StockAdjustment.objects.create(
            product=instance,
            adjustment_type=StockAdjustment.TYPE_OPENING,
            quantity_change=instance.stock,
            quantity_before=0,
            quantity_after=instance.stock,
            note="Opening stock set on product creation.",
        )
        logger.debug(
            "Opening stock adjustment created for product '%s': %d units.",
            instance.name,
            instance.stock,
        )
