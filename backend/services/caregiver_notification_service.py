"""
caregiver_notification_service.py
All caregiver WhatsApp notification templates and send logic.
Each function formats the message, sends via Twilio WhatsApp,
marks the job as notified, and appends to the in-memory alert feed.
"""

import datetime
import logging
from sqlalchemy.orm import Session

from database import ReminderJob, CallLog, CallStatus
from services import twilio_service

logger = logging.getLogger("LastMileMeds.caregiver_notification")

# In-memory alert feed shared with the dashboard endpoint.
# Imported by main.py:  from services.caregiver_notification_service import whatsapp_alerts
whatsapp_alerts: list[dict] = []


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def _medicine_cue(job: ReminderJob) -> str:
    """Return medicine_cue if set, otherwise fall back to description."""
    return (job.medicine.medicine_cue or job.medicine.description or job.medicine.name).strip()


def _scheduled_time_str(job: ReminderJob) -> str:
    return job.scheduled_time.strftime("%I:%M %p")


def _send(job: ReminderJob, message: str, db: Session) -> None:
    """Send WhatsApp, push to alert feed, mark job notified."""
    to = job.elderly.caregiver_whatsapp
    twilio_service.send_whatsapp(to, message)

    whatsapp_alerts.append({
        "id": len(whatsapp_alerts) + 1,
        "to": to,
        "patient_name": job.elderly.name,
        "message": message,
        "timestamp": datetime.datetime.utcnow().isoformat(),
    })

    job.caregiver_notified = True
    db.commit()
    logger.info(f"Caregiver notified for job {job.id} → {to}")


# ─────────────────────────────────────────────────────────
# Per-event notification functions
# ─────────────────────────────────────────────────────────

def notify_confirmed(job: ReminderJob, db: Session) -> None:
    """Case 1 — Medication confirmed by patient."""
    msg = (
        f"✅ {job.elderly.name} has confirmed taking the "
        f"{_medicine_cue(job)} scheduled for {_scheduled_time_str(job)}."
    )
    _send(job, msg, db)


def notify_first_miss(job: ReminderJob, db: Session) -> None:
    """Case 2 — First call missed; retry in 5 minutes."""
    msg = (
        f"ℹ️ {job.elderly.name} did not answer the {_scheduled_time_str(job)} "
        f"reminder call. The system will try again in 5 minutes."
    )
    _send(job, msg, db)


def notify_second_miss(job: ReminderJob, db: Session) -> None:
    """Case 3 — Second call missed; final retry scheduled."""
    msg = (
        f"ℹ️ {job.elderly.name} missed the second reminder call for the "
        f"{_medicine_cue(job)}. One final attempt will be made shortly."
    )
    _send(job, msg, db)


def notify_all_failed(job: ReminderJob, db: Session) -> None:
    """Case 4 — All 3 call attempts failed; caregiver intervention required."""
    msg = (
        f"⚠️ {job.elderly.name} could not be reached after 3 reminder calls "
        f"for the {_scheduled_time_str(job)} medication ({_medicine_cue(job)}). "
        f"Please check on them if possible."
    )
    _send(job, msg, db)


def notify_no_confirmation(job: ReminderJob, db: Session) -> None:
    """Case 5 — Patient answered but did not confirm intake."""
    msg = (
        f"⚠️ {job.elderly.name} answered the reminder call but did not confirm "
        f"taking the {_medicine_cue(job)} scheduled for {_scheduled_time_str(job)}."
    )
    _send(job, msg, db)


def notify_phone_busy(job: ReminderJob, db: Session) -> None:
    """Case 6 — Patient's phone was busy."""
    msg = (
        f"ℹ️ {job.elderly.name}'s phone was busy during the medication reminder "
        f"attempt. The system will retry shortly."
    )
    _send(job, msg, db)


def notify_delivery_failure(job: ReminderJob, db: Session) -> None:
    """Case 7 — Network / Twilio call delivery failure."""
    msg = (
        f"⚠️ We were unable to deliver today's medication reminder call to "
        f"{job.elderly.name} due to a network issue."
    )
    _send(job, msg, db)


# ─────────────────────────────────────────────────────────
# Summary notifications
# ─────────────────────────────────────────────────────────

def send_daily_summary(db: Session) -> None:
    """
    Send a daily medication adherence summary to every caregiver at 9 PM.
    Groups jobs by elderly patient and counts confirmed vs total for today.
    """
    today = datetime.date.today()
    from database import Elderly, ReminderJob as RJ

    all_elderly = db.query(Elderly).all()
    for elderly in all_elderly:
        if not elderly.caregiver_whatsapp:
            continue

        today_jobs = [
            j for j in elderly.reminder_jobs
            if j.scheduled_time and j.scheduled_time.date() == today
        ]
        if not today_jobs:
            continue

        total = len(today_jobs)
        confirmed = sum(1 for j in today_jobs if j.status == CallStatus.CONFIRMED)

        msg = (
            f"📊 Daily Summary:\n"
            f"{elderly.name} successfully took {confirmed} out of {total} "
            f"scheduled medication{'s' if total != 1 else ''} today."
        )
        twilio_service.send_whatsapp(elderly.caregiver_whatsapp, msg)
        whatsapp_alerts.append({
            "id": len(whatsapp_alerts) + 1,
            "to": elderly.caregiver_whatsapp,
            "patient_name": elderly.name,
            "message": msg,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        })
        logger.info(f"Daily summary sent for {elderly.name} → {elderly.caregiver_whatsapp}")


def send_weekly_summary(db: Session) -> None:
    """
    Send a weekly medication adherence summary to every caregiver every Sunday.
    Calculates adherence % over the past 7 days.
    """
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=6)

    from database import Elderly

    all_elderly = db.query(Elderly).all()
    for elderly in all_elderly:
        if not elderly.caregiver_whatsapp:
            continue

        week_jobs = [
            j for j in elderly.reminder_jobs
            if j.scheduled_time and week_start <= j.scheduled_time.date() <= today
        ]
        if not week_jobs:
            continue

        total = len(week_jobs)
        confirmed = sum(1 for j in week_jobs if j.status == CallStatus.CONFIRMED)
        pct = round((confirmed / total) * 100) if total > 0 else 0

        msg = (
            f"📈 Weekly Summary:\n"
            f"{elderly.name} maintained a {pct}% medication adherence rate this week."
        )
        twilio_service.send_whatsapp(elderly.caregiver_whatsapp, msg)
        whatsapp_alerts.append({
            "id": len(whatsapp_alerts) + 1,
            "to": elderly.caregiver_whatsapp,
            "patient_name": elderly.name,
            "message": msg,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        })
        logger.info(f"Weekly summary sent for {elderly.name} → {elderly.caregiver_whatsapp}")
