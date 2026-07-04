"""
call_service.py
Outbound call orchestration and state-machine for retry/escalation logic.

State transitions handled here:
  PENDING → CALLING → ANSWERED → WAITING_CONFIRMATION → CONFIRMED
                                                       → UNCONFIRMED → CAREGIVER_NOTIFIED
                    → NO_ANSWER / BUSY / FAILED
                         └─ attempt < 3 → RETRYING → CALLING (loop)
                         └─ attempt = 3 → FAILED → CAREGIVER_NOTIFIED
"""

import datetime
import logging
import os

from sqlalchemy.orm import Session

from database import SessionLocal, ReminderJob, CallLog, CallStatus
from services import twilio_service
from services import caregiver_notification_service as notifier

logger = logging.getLogger("LastMileMeds.call_service")

# Shared active-calls feed for the simulator panel (populated by trigger_outbound_call).
# Imported by main.py: from services.call_service import active_calls
active_calls: list[dict] = []

# Retry delays
RETRY_DELAY_FIRST_SECONDS = 5 * 60    # 5 minutes after attempt 1
RETRY_DELAY_SECOND_SECONDS = 10 * 60  # 10 minutes after attempt 2

# How long to wait for confirmation before treating as UNCONFIRMED
CONFIRMATION_TIMEOUT_MINUTES = 15

# Language scripts for TwiML and simulator panel
LANGUAGE_SCRIPTS: dict[str, dict] = {
    "English": {
        "greeting": "Hello, this is LastMile Meds calling.",
        "prompt_tpl": "It is time to take your medicine, {name}. Please take {dosage}. It is a {description}.",
        "action": "Please press 1 on your telephone keypad to confirm you have taken your medicine.",
        "thanks": "Thank you. Your medication confirmation has been logged. Have a wonderful day.",
        "voice": "Polly.Amy",
        "language": "en-GB",
    },
    "Hindi": {
        "greeting": "नमस्ते, यह लास्टमाइल मेड्स की कॉल है।",
        "prompt_tpl": "आपकी दवाई {name} लेने का समय हो गया है। कृपया {dosage} लें। यह {description} है।",
        "action": "दवाई लेने की पुष्टि करने के लिए कृपया अपने फोन पर 1 दबाएं।",
        "thanks": "धन्यवाद। आपकी दवाई की पुष्टि दर्ज कर ली गई है। आपका दिन शुभ हो।",
        "voice": "Polly.Aditi",
        "language": "hi-IN",
    },
    "Kannada": {
        "greeting": "ನಮಸ್ತೆ, ಇದು ಲಾಸ್ಟ್\u200cಮೈಲ್ ಮೆಡ್ಸ್ ಕರೆ.",
        "prompt_tpl": "ನಿಮ್ಮ ಔಷಧ {name} ತೆಗೆದುಕೊಳ್ಳುವ ಸಮಯವಾಗಿದೆ. ದಯವಿಟ್ಟು {dosage} ತಗೊಳ್ಳಿ. ಇದು {description}.",
        "action": "ಔಷಧ ತೆಗೆದುಕೊಂಡಿದ್ದೀರಿ ಎಂದು ಖಚಿತಪಡಿಸಲು ದಯವಿಟ್ಟು ಫೋನ್\u200cನಲ್ಲಿ 1 ಒತ್ತಿರಿ.",
        "thanks": "ಧನ್ಯವಾದಗಳು. ನಿಮ್ಮ ಔಷಧಿಯ ವಿವರಗಳನ್ನು ಯಶಸ್ವಿಯಾಗಿ ನಮೂದಿಸಲಾಗಿದೆ. ದಿನ ಶುಭವಾಗಿರಲಿ.",
        "voice": "Google.kn-IN-Standard-A",
        "language": "kn-IN",
    },
    "Telugu": {
        "greeting": "నమస్కారం, ఇది లాస్ట్\u200cమైల్ మెడ్స్ కాల్.",
        "prompt_tpl": "మీ మందు {name} తీసుకునే సమయం ఆసన్నమైంది. దయచేసి {dosage} తీసుకోండి. ఇది {description}.",
        "action": "మందు తీసుకున్నట్లు నిర్ధారించడానికి దయచేసి మీ ఫోన్\u200cలో 1 నొక్కండి.",
        "thanks": "ధన్యవాదాలు. మీ మందు తీసుకున్నారని నమోదు చేయబడింది.",
        "voice": "Google.te-IN-Standard-A",
        "language": "te-IN",
    },
    "Tamil": {
        "greeting": "வணக்கம், இது லாஸ்ட்மைல் மெட்ஸ் அழைப்பு.",
        "prompt_tpl": "உங்கள் மருந்து {name} எடுத்துக்கொள்ள வேண்டிய நேரம் இது. தயவுசெய்து {dosage} எடுத்துக் கொள்ளுங்கள். இது {description}.",
        "action": "மருந்து எடுத்துக்கொண்டதை உறுதிப்படுத்த உங்கள் தொலைபேசியில் 1 ஐ அழுத்தவும்.",
        "thanks": "நன்றி. உங்கள் மருந்து உறுதிப்படுத்தல் பதிவு செய்யப்பட்டது.",
        "voice": "Google.ta-IN-Standard-A",
        "language": "ta-IN",
    },
    "Marathi": {
        "greeting": "नमस्कार, हा लास्टमाईल मेड्सचा कॉल आहे.",
        "prompt_tpl": "तुमचे {name} औषध घेण्याची वेळ झाली आहे. कृपया {dosage} घ्या. हे {description} आहे.",
        "action": "औषध घेतल्याची पुष्टी करण्यासाठी कृपया तुमच्या फोनवर 1 दाबा.",
        "thanks": "धन्यवाद. तुमच्या औषधाची नोंद घेण्यात आली आहे.",
        "voice": "Google.mr-IN-Standard-A",
        "language": "mr-IN",
    },
    "Bengali": {
        "greeting": "নমস্কার, এটি লাস্টমাইল মেডস-এর কল।",
        "prompt_tpl": "আপনার ওষুধ {name} নেওয়ার সময় হয়েছে। অনুগ্রহ করে {dosage} নিন। এটি {description}।",
        "action": "ওষুধ নেওয়ার বিষয়টি নিশ্চিত করতে অনুগ্রহ করে আপনার ফোনে 1 টিপুন।",
        "thanks": "ধন্যবাদ। আপনার ওষুধ গ্রহণ নিশ্চিত হয়েছে।",
        "voice": "Google.bn-IN-Standard-A",
        "language": "bn-IN",
    },
    "Malayalam": {
        "greeting": "നമസ്കാരം, ഇത് ലാസ്റ്റ്മൈൽ മെഡ്സ് കോളാണ്.",
        "prompt_tpl": "നിങ്ങളുടെ മരുന്ന് {name} കഴിക്കാനുള്ള സമയമായി. ദയവായി {dosage} കഴിക്കുക. ഇത് {description} ആണ്.",
        "action": "മരുന്ന് കഴിച്ചുവെന്ന് ഉറപ്പാക്കാൻ ദയവായി നിങ്ങളുടെ ഫോണിൽ 1 അമർത്തുക.",
        "thanks": "നന്ദി. നിങ്ങളുടെ മരുന്ന് ഉറപ്പ് രേഖപ്പെടുത്തി.",
        "voice": "Google.ml-IN-Standard-A",
        "language": "ml-IN",
    },
}


def get_language_script(language: str) -> dict:
    return LANGUAGE_SCRIPTS.get(language, LANGUAGE_SCRIPTS["English"])


def trigger_outbound_call(job_id: int) -> None:
    """
    Place an outbound call for a reminder job.
    Updates job status → CALLING, increments attempt_count,
    pushes to active_calls feed, and fires Twilio (or simulates).
    """
    db = SessionLocal()
    try:
        job = db.query(ReminderJob).filter(ReminderJob.id == job_id).first()
        if not job:
            logger.warning(f"trigger_outbound_call: job {job_id} not found")
            return

        # Update job state
        job.status = CallStatus.CALLING
        job.attempt_count += 1
        job.last_attempt_time = datetime.datetime.utcnow()
        db.commit()
        db.refresh(job)

        # Remove any stale entry for this job from the active-calls feed
        global active_calls
        active_calls = [c for c in active_calls if c["job_id"] != job_id]

        lang = get_language_script(job.elderly.language)
        prompt = lang["prompt_tpl"].format(
            name=job.medicine.name,
            dosage=job.medicine.dosage,
            description=job.medicine.description,
        )
        greeting = (
            job.elderly.greeting_audio_url
            if job.elderly.greeting_audio_url and job.elderly.greeting_audio_url.startswith("http")
            else lang["greeting"]
        )

        # Push to simulator panel
        active_calls.append({
            "job_id": job.id,
            "patient_name": job.elderly.name,
            "patient_phone": job.elderly.phone,
            "language": job.elderly.language,
            "medicine_name": job.medicine.name,
            "dosage": job.medicine.dosage,
            "description": job.medicine.description,
            "medicine_cue": job.medicine.medicine_cue or job.medicine.description,
            "greeting": greeting,
            "prompt": prompt,
            "action_prompt": lang["action"],
            "attempt": job.attempt_count,
        })

        # Place real Twilio call
        base_url = os.getenv("BASE_URL", os.getenv("SERVER_URL", "http://localhost:8000"))
        twiml_url = f"{base_url}/api/twilio/voice-twiml/{job.id}"
        status_cb = f"{base_url}/api/twilio/status-callback/{job.id}"

        call_sid = twilio_service.make_voice_call(job.elderly.phone, twiml_url, status_cb)
        if call_sid:
            job.call_sid = call_sid
            db.commit()

        logger.info(f"Outbound call triggered for job {job_id} (attempt {job.attempt_count})")
    finally:
        db.close()


def process_call_outcome(job_id: int, outcome: str, call_sid: str | None = None) -> None:
    """
    Central state-machine handler for all call outcomes.

    outcome values:
        "no-answer"  — Twilio status-callback or Gather timeout
        "busy"       — Twilio status-callback
        "failed"     — Twilio delivery failure
        "confirmed"  — Patient pressed 1
        "unconfirmed"— Patient answered but confirmation window expired
        "hangup"     — Patient hung up without pressing anything
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    # Import scheduler lazily to avoid circular imports
    from services.scheduler_service import get_scheduler

    db = SessionLocal()
    try:
        job = db.query(ReminderJob).filter(ReminderJob.id == job_id).first()
        if not job:
            logger.warning(f"process_call_outcome: job {job_id} not found")
            return

        # Track call SID
        if call_sid:
            job.call_sid = call_sid

        outcome_lower = outcome.lower()

        # ── CONFIRMED ────────────────────────────────────────────────────────
        if outcome_lower == "confirmed":
            job.status = CallStatus.CONFIRMED
            job.last_call_status = CallStatus.ANSWERED
            job.confirmation_status = "CONFIRMED"
            job.confirmation_timestamp = datetime.datetime.utcnow()

            log = CallLog(
                reminder_job_id=job.id,
                attempt_num=job.attempt_count,
                status=CallStatus.CONFIRMED,
                confirmed=True,
                details="Patient confirmed via keypad press 1.",
                call_sid=call_sid,
            )
            db.add(log)
            db.commit()

            notifier.notify_confirmed(job, db)
            logger.info(f"Job {job_id}: CONFIRMED")
            return

        # ── UNCONFIRMED (answered but no confirmation after timeout) ─────────
        if outcome_lower == "unconfirmed":
            job.status = CallStatus.UNCONFIRMED
            job.last_call_status = CallStatus.ANSWERED
            job.confirmation_status = "UNCONFIRMED"

            log = CallLog(
                reminder_job_id=job.id,
                attempt_num=job.attempt_count,
                status=CallStatus.UNCONFIRMED,
                confirmed=False,
                details="Patient answered but did not confirm within the timeout window.",
                call_sid=call_sid,
            )
            db.add(log)
            db.commit()

            notifier.notify_no_confirmation(job, db)
            job.status = CallStatus.CAREGIVER_NOTIFIED
            db.commit()
            logger.info(f"Job {job_id}: UNCONFIRMED → caregiver notified")
            return

        # ── NO-ANSWER / BUSY / FAILED / HANGUP ──────────────────────────────
        if outcome_lower in ("busy",):
            log_status = CallStatus.BUSY
            job.last_call_status = CallStatus.BUSY
        elif outcome_lower in ("failed",):
            log_status = CallStatus.FAILED
            job.last_call_status = CallStatus.FAILED
        else:
            # no-answer, hangup, or anything else
            log_status = CallStatus.NO_ANSWER
            job.last_call_status = CallStatus.NO_ANSWER

        log = CallLog(
            reminder_job_id=job.id,
            attempt_num=job.attempt_count,
            status=log_status,
            confirmed=False,
            details=f"Call outcome: {outcome}",
            call_sid=call_sid,
        )
        db.add(log)

        # ── Delivery failure (never even connected) ──────────────────────────
        if log_status == CallStatus.FAILED:
            job.status = CallStatus.FAILED
            job.failure_reason = f"Delivery failure on attempt {job.attempt_count}: {outcome}"
            db.commit()
            notifier.notify_delivery_failure(job, db)
            job.status = CallStatus.CAREGIVER_NOTIFIED
            db.commit()
            logger.info(f"Job {job_id}: delivery FAILED → caregiver notified")
            return

        # ── Busy: notify caregiver and schedule a retry ──────────────────────
        if log_status == CallStatus.BUSY:
            db.commit()
            notifier.notify_phone_busy(job, db)
            # Treat busy like no-answer for retry counting

        # ── Retry logic ──────────────────────────────────────────────────────
        if job.attempt_count < 3:
            job.status = CallStatus.RETRYING
            job.failure_reason = f"Attempt {job.attempt_count} failed: {outcome}"
            db.commit()

            # Notify caregiver of intermediate missed calls
            if job.attempt_count == 1:
                notifier.notify_first_miss(job, db)
                delay_secs = RETRY_DELAY_FIRST_SECONDS
            elif job.attempt_count == 2:
                notifier.notify_second_miss(job, db)
                delay_secs = RETRY_DELAY_SECOND_SECONDS
            else:
                delay_secs = RETRY_DELAY_SECOND_SECONDS

            run_at = datetime.datetime.now() + datetime.timedelta(seconds=delay_secs)
            sched = get_scheduler()
            sched.add_job(
                trigger_outbound_call,
                "date",
                run_date=run_at,
                args=[job_id],
                id=f"retry_{job_id}_attempt_{job.attempt_count + 1}",
                replace_existing=True,
            )
            logger.info(f"Job {job_id}: retry {job.attempt_count + 1} scheduled at {run_at}")

        else:
            # All 3 attempts exhausted
            job.status = CallStatus.FAILED
            job.failure_reason = f"Exhausted 3 attempts. Last error: {outcome}"
            db.commit()
            notifier.notify_all_failed(job, db)
            job.status = CallStatus.CAREGIVER_NOTIFIED
            db.commit()
            logger.info(f"Job {job_id}: all attempts FAILED → caregiver notified")

    finally:
        db.close()
