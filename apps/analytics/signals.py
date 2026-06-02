"""
apps/analytics/signals.py

Django signals for keeping DailySummary in sync.

When a Transaction is saved (created or updated), we trigger a rebuild
of the DailySummary for that transaction's date and store.

This means:
  - When a cashier completes a sale → today's summary is updated instantly
  - When a manager processes a refund → today's summary is recalculated
  - Summary is always up-to-date without waiting for a nightly cron job

The rebuild is synchronous and lightweight (aggregates a single day).
For high-throughput stores, this could be moved to a Celery task.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def connect_signals():
    """
    Wire up the Transaction post_save signal.

    Called from AnalyticsConfig.ready() to avoid circular imports.
    The Transaction model is imported inside the function for the same reason.
    """
    from apps.transactions.models import Transaction

    @receiver(post_save, sender=Transaction)
    def on_transaction_saved(sender, instance, created, **kwargs):
        """
        Rebuild DailySummary whenever a transaction is saved.

        This handles:
          - New sales (created=True)
          - Status changes (paid → refunded)
        """
        from apps.analytics.services import rebuild_daily_summary

        try:
            target_date = instance.created_at.date()
            rebuild_daily_summary(store=instance.store, target_date=target_date)
            logger.debug(
                "DailySummary rebuilt for store=%s date=%s after transaction %s",
                instance.store_id, target_date, instance.txn_number,
            )
        except Exception as exc:
            # Never crash a sale because analytics couldn't update
            logger.warning(
                "Failed to rebuild DailySummary for %s: %s",
                instance.txn_number, exc,
            )
