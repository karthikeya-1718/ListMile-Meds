"""
scheduler_service.py
Central APScheduler configuration.

Exposes:
    get_scheduler()  — returns the singleton BackgroundScheduler instance
    init_scheduler() — registers all recurring jobs and starts the scheduler
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger("LastMileMeds.scheduler_service")

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    """Return the singleton scheduler, creating it if needed."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def init_scheduler() -> BackgroundScheduler:
    """
    Register all recurring jobs and start the scheduler.
    Called once from main.py at application startup.
    """
    sched = get_scheduler()

    if sched.running:
        logger.info("Scheduler already running — skipping re-init.")
        return sched

    # ── Every-minute ticks ────────────────────────────────────────────────────
    # Check for PENDING reminder jobs whose scheduled_time has arrived.
    from services.reminder_service import check_pending_reminders
    sched.add_job(
        check_pending_reminders,
        "interval",
        minutes=1,
        id="check_pending_reminders",
        replace_existing=True,
    )

    # Check WAITING_CONFIRMATION jobs that have timed out (> 15 min with no press).
    from services.reminder_service import check_unconfirmed_answered_calls
    sched.add_job(
        check_unconfirmed_answered_calls,
        "interval",
        minutes=1,
        id="check_unconfirmed_calls",
        replace_existing=True,
    )

    # ── Daily summary — 9 PM every day ───────────────────────────────────────
    def _daily_summary_job():
        from database import SessionLocal
        from services.caregiver_notification_service import send_daily_summary
        db = SessionLocal()
        try:
            send_daily_summary(db)
        finally:
            db.close()

    sched.add_job(
        _daily_summary_job,
        "cron",
        hour=21,
        minute=0,
        id="daily_summary",
        replace_existing=True,
    )

    # ── Weekly summary — every Sunday at 9 PM ────────────────────────────────
    def _weekly_summary_job():
        from database import SessionLocal
        from services.caregiver_notification_service import send_weekly_summary
        db = SessionLocal()
        try:
            send_weekly_summary(db)
        finally:
            db.close()

    sched.add_job(
        _weekly_summary_job,
        "cron",
        day_of_week="sun",
        hour=21,
        minute=0,
        id="weekly_summary",
        replace_existing=True,
    )

    sched.start()
    logger.info("Scheduler started with jobs: check_pending_reminders, check_unconfirmed_calls, daily_summary, weekly_summary")
    return sched
