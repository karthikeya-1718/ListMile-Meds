"""
reminder_service.py
Scheduler tick functions called every minute by the APScheduler jobs.

check_pending_reminders()
    — Finds PENDING/SCHEDULED jobs whose scheduled_time has arrived and triggers calls.

check_unconfirmed_answered_calls()
    — Finds WAITING_CONFIRMATION jobs older than 15 minutes and escalates them.
"""

import datetime
import logging

from database import SessionLocal, ReminderJob, CallStatus
from services.call_service import process_call_outcome

logger = logging.getLogger("LastMileMeds.reminder_service")

CONFIRMATION_TIMEOUT_MINUTES = 15


def check_pending_reminders() -> None:
    """
    Called every minute by the scheduler.
    Queries for PENDING jobs whose scheduled_time is now (or up to 90 seconds past)
    and triggers an outbound call for each.
    """
    db = SessionLocal()
    try:
        now = datetime.datetime.utcnow()
        # Window: jobs due in the last 90 seconds that haven't been picked up yet
        window_start = now - datetime.timedelta(seconds=90)

        due_jobs = (
            db.query(ReminderJob)
            .filter(
                ReminderJob.status == CallStatus.PENDING,
                ReminderJob.scheduled_time >= window_start,
                ReminderJob.scheduled_time <= now,
            )
            .all()
        )

        for job in due_jobs:
            logger.info(f"Scheduler: triggering call for job {job.id} ({job.elderly.name})")
            from services.call_service import trigger_outbound_call
            trigger_outbound_call(job.id)

    except Exception as e:
        logger.error(f"check_pending_reminders error: {e}")
    finally:
        db.close()


def check_unconfirmed_answered_calls() -> None:
    """
    Called every minute by the scheduler.
    Finds jobs in WAITING_CONFIRMATION status where the last attempt was more than
    CONFIRMATION_TIMEOUT_MINUTES ago and escalates them as UNCONFIRMED.
    """
    db = SessionLocal()
    try:
        now = datetime.datetime.utcnow()
        cutoff = now - datetime.timedelta(minutes=CONFIRMATION_TIMEOUT_MINUTES)

        waiting_jobs = (
            db.query(ReminderJob)
            .filter(
                ReminderJob.status == CallStatus.WAITING_CONFIRMATION,
                ReminderJob.last_attempt_time <= cutoff,
            )
            .all()
        )

        for job in waiting_jobs:
            logger.info(
                f"Scheduler: confirmation timeout for job {job.id} ({job.elderly.name})"
            )
            process_call_outcome(job.id, "unconfirmed")

    except Exception as e:
        logger.error(f"check_unconfirmed_answered_calls error: {e}")
    finally:
        db.close()
