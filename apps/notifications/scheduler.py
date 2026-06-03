"""
apps/notifications/scheduler.py

APScheduler configuration for Ziada's background jobs.

Jobs:
  daily_sales_report — fires every day at 22:00 Africa/Dar_es_Salaam
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution

logger = logging.getLogger(__name__)

_scheduler = None


def _run_daily_sales_report():
    """Job function — called by APScheduler at 22:00 EAT."""
    from .emails import send_daily_sales_report
    logger.info("Running scheduled daily sales report...")
    count = send_daily_sales_report()
    logger.info("Daily sales report sent to %d stores.", count)


def delete_old_executions(max_age: int = 7) -> None:
    """Purge APScheduler execution records older than `max_age` days."""
    DjangoJobExecution.objects.delete_old_job_executions(max_age * 24 * 3600)


def start_scheduler():
    """
    Start the APScheduler background scheduler.
    Safe to call multiple times — only creates the scheduler once.
    Uses Africa/Dar_es_Salaam (EAT, UTC+3) for the cron trigger.
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    hour   = getattr(settings, "DAILY_REPORT_HOUR",   22)
    minute = getattr(settings, "DAILY_REPORT_MINUTE",  0)

    _scheduler = BackgroundScheduler(timezone="Africa/Dar_es_Salaam")
    _scheduler.add_jobstore(DjangoJobStore(), "default")

    # Daily sales report — every day at configured hour:minute EAT
    _scheduler.add_job(
        func=_run_daily_sales_report,
        trigger=CronTrigger(hour=hour, minute=minute, timezone="Africa/Dar_es_Salaam"),
        id="daily_sales_report",
        name="Daily sales report",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,  # 5-minute grace window
    )

    # Cleanup old execution records once a day at 23:00
    _scheduler.add_job(
        func=delete_old_executions,
        trigger=CronTrigger(hour=23, minute=0, timezone="Africa/Dar_es_Salaam"),
        id="cleanup_apscheduler",
        name="Cleanup APScheduler records",
        replace_existing=True,
    )

    try:
        _scheduler.start()
        logger.info(
            "APScheduler started. Daily sales report at %02d:%02d EAT.",
            hour, minute,
        )
    except Exception as exc:
        logger.error("APScheduler failed to start: %s", exc)
