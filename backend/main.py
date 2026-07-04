import datetime
import logging
import os
import json
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Form, File, UploadFile, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from twilio.twiml.voice_response import VoiceResponse
import google.generativeai as genai

from database import SessionLocal, init_db, User, Elderly, Medicine, ReminderJob, CallLog, CallStatus
from services import call_service, caregiver_notification_service as notifier
from services.call_service import active_calls, get_language_script
from services.caregiver_notification_service import whatsapp_alerts
from services.scheduler_service import init_scheduler

# Load variables from .env file
load_dotenv()

# Configure Gemini Generative AI
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LastMileMeds")

init_db()

app = FastAPI(title="LastMile Meds Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://list-mile-meds.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base URL to reach this FastAPI server (needed for Twilio Webhook callbacks)
BASE_URL = os.getenv("BASE_URL", os.getenv("SERVER_URL", "http://localhost:8000"))

# Initialise APScheduler with all recurring jobs via scheduler_service
scheduler = init_scheduler()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Pydantic Schemas
class MedicineBase(BaseModel):
    name: str
    dosage: str
    frequency: str
    time: str
    duration: str
    description: str
    medicine_cue: Optional[str] = None  # caregiver recognition cue for notifications

class MedicineCreate(MedicineBase):
    pass

class MedicineResponse(MedicineBase):
    id: int
    elderly_id: int
    class Config:
        from_attributes = True

class ElderlyCreate(BaseModel):
    name: str
    phone: str
    language: str = "English"
    caregiver_whatsapp: str
    greeting_audio_url: Optional[str] = None

class ElderlyResponse(BaseModel):
    id: int
    name: str
    phone: str
    language: str
    caregiver_whatsapp: str
    greeting_audio_url: Optional[str] = None
    medicines: List[MedicineResponse] = []
    class Config:
        from_attributes = True

class CallLogResponse(BaseModel):
    id: int
    reminder_job_id: int
    timestamp: datetime.datetime
    attempt_num: int
    status: str
    confirmed: bool
    details: Optional[str] = None
    class Config:
        from_attributes = True

class ReminderJobResponse(BaseModel):
    id: int
    elderly_id: int
    medicine_id: int
    scheduled_time: datetime.datetime
    status: str
    attempt_count: int
    last_attempt_time: Optional[datetime.datetime] = None
    failure_reason: Optional[str] = None
    medicine: Optional[MedicineResponse] = None
    elderly: Optional[ElderlyResponse] = None
    call_logs: List[CallLogResponse] = []
    class Config:
        from_attributes = True

# ─────────────────────────────────────────────────────────────────────────────
# Twilio Voice Webhook Callbacks
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/twilio/voice-twiml/{job_id}")
def get_voice_twiml(job_id: int, db: Session = Depends(get_db)):
    """
    Triggers a real Twilio Voice Call if client is configured.
    Falls back to Simulation if keys are missing.
    """
    db = SessionLocal()
    job = db.query(ReminderJob).filter(ReminderJob.id == job_id).first()
    if not job:
        db.close()
        return

    job.status = "CALLING"
    job.attempt_count += 1
    job.last_attempt_time = datetime.datetime.utcnow()
    db.commit()

    global active_calls
    active_calls = [c for c in active_calls if c["job_id"] != job_id]

    language_greetings = {
        "English": {
            "greeting": "Hello, this is LastMile Meds calling.",
            "prompt": f"It is time to take your medicine, {job.medicine.name}. Please take {job.medicine.dosage}. It is a {job.medicine.description}.",
            "action": "Please press 1 on your telephone keypad to confirm you have taken your medicine."
        },
        "Hindi": {
            "greeting": "नमस्ते, यह लास्टमाइल मेड्स की कॉल है।",
            "prompt": f"आपकी दवाई {job.medicine.name} लेने का समय हो गया है। कृपया {job.medicine.dosage} लें। यह {job.medicine.description} है।",
            "action": "दवाई लेने की पुष्टि करने के लिए कृपया अपने फोन पर 1 दबाएं।"
        },
        "Kannada": {
            "greeting": "ನಮಸ್ತೆ, ಇದು ಲಾಸ್ಟ್‌ಮೈಲ್ ಮೆಡ್ಸ್ ಕರೆ.",
            "prompt": f"ನಿಮ್ಮ ಔಷಧ {job.medicine.name} ತೆಗೆದುಕೊಳ್ಳುವ ಸಮಯವಾಗಿದೆ. ದಯವಿಟ್ಟು {job.medicine.dosage} ತಗೊಳ್ಳಿ. ಇದು {job.medicine.description}.",
            "action": f"ಔಷಧ ತೆಗೆದುಕೊಂಡಿದ್ದೀರಿ ಎಂದು ಖಚಿತಪಡಿಸಲು ದಯವಿಟ್ಟು ಫೋನ್‌ನಲ್ಲಿ 1 ಒತ್ತಿರಿ."
        },
        "Telugu": {
            "greeting": "నమస్కారం, ఇది లాస్ట్‌మైల్ మెడ్స్ కాల్.",
            "prompt": f"మీ మందు {job.medicine.name} తీసుకునే సమయం ఆసన్నమైంది. దయచేసి {job.medicine.dosage} తీసుకోండి. ఇది {job.medicine.description}.",
            "action": "మందు తీసుకున్నట్లు నిర్ధారించడానికి దయచేసి మీ ఫోన్‌లో 1 నొక్కండి."
        },
        "Tamil": {
            "greeting": "வணக்கம், இது லாஸ்ட்மைல் மெட்ஸ் அழைப்பு.",
            "prompt": f"உங்கள் மருந்து {job.medicine.name} எடுத்துக்கொள்ள வேண்டிய நேரம் இது. தயவுசெய்து {job.medicine.dosage} எடுத்துக் கொள்ளுங்கள். இது {job.medicine.description}.",
            "action": "மருந்து எடுத்துக்கொண்டதை உறுதிப்படுத்த உங்கள் தொலைபேசியில் 1 ஐ அழுத்தவும்."
        },
        "Marathi": {
            "greeting": "नमस्कार, हा लास्टमाईल मेड्सचा कॉल आहे.",
            "prompt": f"तुमचे {job.medicine.name} औषध घेण्याची वेळ झाली आहे. कृपया {job.medicine.dosage} घ्या. हे {job.medicine.description} आहे.",
            "action": "औषध घेतल्याची पुष्टी करण्यासाठी कृपया तुमच्या फोनवर 1 दाबा."
        },
        "Bengali": {
            "greeting": "নমস্কার, এটি লাস্টমাইল মেডস-এর কল।",
            "prompt": f"আপনার ওষুধ {job.medicine.name} নেওয়ার সময় হয়েছে। অনুগ্রহ করে {job.medicine.dosage} নিন। এটি {job.medicine.description}।",
            "action": "ওষুধ নেওয়ার বিষয়টি নিশ্চিত করতে অনুগ্রহ করে আপনার ফোনে 1 টিপুন।"
        },
        "Malayalam": {
            "greeting": "നമസ്കാരം, ഇത് ലാസ്റ്റ്മൈൽ മെഡ്സ് കോളാണ്.",
            "prompt": f"നിങ്ങളുടെ മരുന്ന് {job.medicine.name} കഴിക്കാനുള്ള സമയമായി. ദയവായി {job.medicine.dosage} കഴിക്കുക. ഇത് {job.medicine.description} ആണ്.",
            "action": "മരുന്ന് കഴിച്ചുവെന്ന് ഉറപ്പാക്കാൻ ദയവായി നിങ്ങളുടെ ഫോണിൽ 1 അമർത്തുക."
        }
    }
    
    lang_info = language_greetings.get(job.elderly.language, language_greetings["English"])
    greeting_voice = job.elderly.greeting_audio_url if job.elderly.greeting_audio_url else lang_info["greeting"]

    # Save to simulator screen state too (so dashboard still monitors it live)
    active_calls.append({
        "job_id": job.id,
        "patient_name": job.elderly.name,
        "patient_phone": job.elderly.phone,
        "language": job.elderly.language,
        "medicine_name": job.medicine.name,
        "dosage": job.medicine.dosage,
        "description": job.medicine.description,
        "greeting": greeting_voice,
        "prompt": lang_info["prompt"],
        "action_prompt": lang_info["action"],
        "attempt": job.attempt_count
    })

    if twilio_client and TWILIO_PHONE_NUMBER:
        try:
            # Outbound call webhook URL for Twilio instructions (TwiML)
            callback_url = f"{BASE_URL}/api/twilio/voice-twiml/{job.id}"
            call = twilio_client.calls.create(
                url=callback_url,
                to=job.elderly.phone,
                from_=TWILIO_PHONE_NUMBER,
                status_callback=f"{BASE_URL}/api/twilio/status-callback/{job.id}",
                status_callback_event=['initiated', 'ringing', 'answered', 'completed']
            )
            logger.info(f"Outbound Twilio Call created: {call.sid} to {job.elderly.phone}")
        except Exception as e:
            logger.error(f"Failed to place real Twilio call: {e}. Falling back to simulation.")
    else:
        logger.info(f"Twilio credentials not fully set up. Simulating Outbound call.")

    db.close()

def process_no_answer_or_hangup(job_id: int, reason: str):
    """
    Implements retry and caregiver escalation state machine logic.
    - Attempt 1: Wait 5 seconds (simulated 5 mins) to retry.
    - Attempt 2: Wait 10 seconds (simulated 10 mins) to retry.
    - Attempt 3: Escalate via WhatsApp.
    """
    db = SessionLocal()
    job = db.query(ReminderJob).filter(ReminderJob.id == job_id).first()
    if not job:
        db.close()
        return

    log = CallLog(
        reminder_job_id=job.id,
        attempt_num=job.attempt_count,
        status="NO_ANSWER" if "answer" in reason.lower() else "HANGUP",
        confirmed=False,
        details=reason
    )
    db.add(log)

    if job.attempt_count < 3:
        job.status = "RETRYING"
        job.failure_reason = f"Attempt {job.attempt_count} failed: {reason}"
        db.commit()
        db.close()
        
        # Schedule retry
        run_time = datetime.datetime.now() + datetime.timedelta(seconds=5)
        scheduler.add_job(trigger_outbound_call, 'date', run_date=run_time, args=[job_id])
        logger.info(f"Scheduled retry attempt {job.attempt_count + 1} for job {job_id}")
    else:
        job.status = "FAILED"
        job.failure_reason = f"Exhausted 3 attempts. Last error: {reason}"
        db.commit()

        whatsapp_msg = (
            f"🚨 LastMile Meds ALERT: {job.elderly.name} missed taking their medication "
            f"'{job.medicine.name}' ({job.medicine.dosage}) scheduled at "
            f"{job.scheduled_time.strftime('%I:%M %p')}. All 3 call attempts failed. Reason: {reason}."
        )

        # Trigger real WhatsApp message if Twilio is active
        if twilio_client and TWILIO_PHONE_NUMBER:
            try:
                # Sandbox Twilio WhatsApp sender prefix is "whatsapp:"
                twilio_client.messages.create(
                    body=whatsapp_msg,
                    from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
                    to=f"whatsapp:{job.elderly.caregiver_whatsapp}"
                )
                logger.info(f"Real WhatsApp Alert sent to {job.elderly.caregiver_whatsapp}")
            except Exception as e:
                logger.error(f"Failed to send real WhatsApp alert: {e}")

        # Feed to dashboard feed
        global whatsapp_alerts
        whatsapp_alerts.append({
            "id": len(whatsapp_alerts) + 1,
            "to": job.elderly.caregiver_whatsapp,
            "patient_name": job.elderly.name,
            "message": whatsapp_msg,
            "timestamp": datetime.datetime.utcnow().isoformat()
        })
        
        job.status = "CAREGIVER_NOTIFIED"
        db.commit()
        db.close()
        logger.info(f"WhatsApp Escalation Sent for job {job_id}")

# --- Twilio Voice Webhook Callbacks ---

@app.post("/api/twilio/voice-twiml/{job_id}")
def get_voice_twiml(job_id: int, db: Session = Depends(get_db)):
    """
    Returns TwiML instructions when a call is answered.
    Greets the patient, reads dosage details, and asks them to press 1 to confirm.
    """
    job = db.query(ReminderJob).filter(ReminderJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Mark job as WAITING_CONFIRMATION (call was answered)
    job.status = CallStatus.WAITING_CONFIRMATION
    job.last_call_status = CallStatus.ANSWERED
    job.last_attempt_time = datetime.datetime.utcnow()
    db.commit()

    lang_info = get_language_script(job.elderly.language)
    prompt = lang_info["prompt_tpl"].format(
        name=job.medicine.name,
        dosage=job.medicine.dosage,
        description=job.medicine.description,
    )

    response = VoiceResponse()

    # Play or speak greeting
    if job.elderly.greeting_audio_url and job.elderly.greeting_audio_url.startswith("http"):
        response.play(job.elderly.greeting_audio_url)
    else:
        response.say(lang_info["greeting"], voice=lang_info["voice"], language=lang_info["language"])

    response.say(prompt, voice=lang_info["voice"], language=lang_info["language"])

    # Gather keypad digit 1
    gather = response.gather(
        num_digits=1,
        action=f"{BASE_URL}/api/twilio/gather-digits/{job.id}",
        method="POST",
        timeout=10,
    )
    gather.say(lang_info["action"], voice=lang_info["voice"], language=lang_info["language"])

    # Redirect to timeout callback if no key is pressed within gather timeout
    response.redirect(f"{BASE_URL}/api/twilio/timeout-callback/{job.id}", method="POST")

    return Response(content=str(response), media_type="application/xml")


@app.post("/api/twilio/gather-digits/{job_id}")
def gather_digits_callback(
    job_id: int,
    Digits: str = Form(None),
    CallSid: str = Form(None),
    db: Session = Depends(get_db),
):
    """
    Processes key presses from the patient.
    '1' → confirmed; anything else → treated as no-confirmation.
    """
    job = db.query(ReminderJob).filter(ReminderJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response = VoiceResponse()

    # Remove from simulator active-calls feed
    call_service.active_calls[:] = [c for c in call_service.active_calls if c["job_id"] != job_id]

    if Digits == "1":
        lang_info = get_language_script(job.elderly.language)
        response.say(lang_info["thanks"], voice=lang_info["voice"], language=lang_info["language"])
        response.hangup()
        # Delegate confirmation to call_service state machine
        call_service.process_call_outcome(job_id, "confirmed", call_sid=CallSid)
    else:
        response.say("We did not receive your confirmation. Goodbye.")
        response.hangup()
        call_service.process_call_outcome(job_id, "no-answer", call_sid=CallSid)

    return Response(content=str(response), media_type="application/xml")


@app.post("/api/twilio/timeout-callback/{job_id}")
def twilio_timeout_callback(job_id: int, CallSid: str = Form(None)):
    """
    Fires when the patient answers but does not press any key within Gather timeout.
    Treated as WAITING_CONFIRMATION (the scheduler will escalate after 15 min).
    """
    # Remove from simulator feed
    call_service.active_calls[:] = [c for c in call_service.active_calls if c["job_id"] != job_id]
    response = VoiceResponse()
    response.say("We did not receive your confirmation. We will try again shortly.")
    response.hangup()
    return Response(content=str(response), media_type="application/xml")


@app.post("/api/twilio/status-callback/{job_id}")
def twilio_status_callback(
    job_id: int,
    CallStatus: str = Form(None),
    CallSid: str = Form(None),
):
    """
    Listens to Twilio Call lifecycle events (no-answer, busy, failed, completed).
    Only terminal failure states are forwarded to the state machine here;
    'completed' after answered is handled by gather-digits / timeout-callback.
    """
    if CallStatus in ("no-answer", "busy", "failed"):
        call_service.process_call_outcome(job_id, CallStatus, call_sid=CallSid)
    return {"status": "ok"}

# --- Dashboard API ---

@app.get("/api/dashboard")
def get_dashboard_data(db: Session = Depends(get_db)):
    total_patients = db.query(Elderly).count()
    active_jobs = db.query(ReminderJob).all()
    
    taken = sum(1 for j in active_jobs if j.status == "CONFIRMED")
    pending = sum(1 for j in active_jobs if j.status in ["PENDING", "CALLING", "WAITING_CONFIRMATION", "RETRYING"])
    missed = sum(1 for j in active_jobs if j.status in ["FAILED", "CAREGIVER_NOTIFIED"])

    logs = db.query(CallLog).order_by(CallLog.timestamp.desc()).limit(15).all()
    
    return {
        "summary": {
            "total_patients": total_patients,
            "taken": taken,
            "pending": pending,
            "missed": missed
        },
        "recent_logs": [
            {
                "id": l.id,
                "timestamp": l.timestamp,
                "patient_name": l.reminder_job.elderly.name,
                "medicine_name": l.reminder_job.medicine.name,
                "attempt_num": l.attempt_num,
                "status": l.status,
                "confirmed": l.confirmed,
                "details": l.details
            } for l in logs if l.reminder_job
        ]
    }

# CRUD: Elderly
@app.get("/api/elderly", response_model=List[ElderlyResponse])
def get_elderly(db: Session = Depends(get_db)):
    return db.query(Elderly).all()

@app.post("/api/elderly", response_model=ElderlyResponse)
def create_elderly(elderly: ElderlyCreate, db: Session = Depends(get_db)):
    user = db.query(User).first()
    db_elderly = Elderly(
        name=elderly.name,
        phone=elderly.phone,
        language=elderly.language,
        caregiver_id=user.id,
        caregiver_whatsapp=elderly.caregiver_whatsapp,
        greeting_audio_url=elderly.greeting_audio_url
    )
    db.add(db_elderly)
    db.commit()
    db.refresh(db_elderly)
    return db_elderly

# CRUD: Medicines
@app.post("/api/elderly/{elderly_id}/medicines", response_model=MedicineResponse)
def add_medicine(elderly_id: int, med: MedicineCreate, db: Session = Depends(get_db)):
    db_med = Medicine(
        elderly_id=elderly_id,
        name=med.name,
        dosage=med.dosage,
        frequency=med.frequency,
        time=med.time,
        duration=med.duration,
        description=med.description,
        medicine_cue=med.medicine_cue,  # optional caregiver recognition cue
    )
    db.add(db_med)
    db.commit()
    db.refresh(db_med)
    
    today = datetime.datetime.now()
    try:
        hour, minute = map(int, med.time.split(":"))
        scheduled_time = datetime.datetime(today.year, today.month, today.day, hour, minute)
        if scheduled_time < today:
            scheduled_time += datetime.timedelta(days=1)
    except Exception:
        scheduled_time = today + datetime.timedelta(minutes=1)

    job = ReminderJob(
        elderly_id=elderly_id,
        medicine_id=db_med.id,
        scheduled_time=scheduled_time,
        status=CallStatus.PENDING,
    )
    db.add(job)
    db.commit()

    scheduler.add_job(
        call_service.trigger_outbound_call,
        "date",
        run_date=scheduled_time,
        args=[job.id],
        id=f"job_{job.id}",
        replace_existing=True,
    )

    return db_med

@app.get("/api/reminders", response_model=List[ReminderJobResponse])
def get_reminders(db: Session = Depends(get_db)):
    return db.query(ReminderJob).order_by(ReminderJob.scheduled_time.desc()).all()

@app.post("/api/reminders/{job_id}/trigger")
def force_trigger_reminder(job_id: int, db: Session = Depends(get_db)):
    job = db.query(ReminderJob).filter(ReminderJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Reminder not found")
    call_service.trigger_outbound_call(job.id)
    return {"message": "Outbound reminder call initiated."}

# Active Calls for Simulator Panel
@app.get("/api/simulator/calls")
def get_simulated_calls():
    return call_service.active_calls


# Twilio Simulator Actions (Press 1 to confirm, Hangup, No Answer)
@app.post("/api/simulator/calls/{job_id}/action")
def simulator_call_action(job_id: int, action: str, db: Session = Depends(get_db)):
    # Remove from active-calls feed
    call_service.active_calls[:] = [c for c in call_service.active_calls if c["job_id"] != job_id]

    job = db.query(ReminderJob).filter(ReminderJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if action == "CONFIRM":
        call_service.process_call_outcome(job_id, "confirmed")
        return {"status": "success", "message": "Medication confirmation received."}

    elif action == "HANGUP":
        call_service.process_call_outcome(job_id, "no-answer")
        return {"status": "retry", "message": "Call hung up. Scheduling retry."}

    elif action == "NO_ANSWER":
        call_service.process_call_outcome(job_id, "no-answer")
        return {"status": "retry", "message": "No answer. Scheduling retry."}

    elif action == "BUSY":
        call_service.process_call_outcome(job_id, "busy")
        return {"status": "retry", "message": "Phone busy. Caregiver notified and retry scheduled."}

    raise HTTPException(status_code=400, detail="Invalid action")


# Caregiver WhatsApp Simulator Alerts
@app.get("/api/simulator/whatsapp")
def get_whatsapp_alerts():
    return notifier.whatsapp_alerts


# ─────────────────────────────────────────────────────────────────────────────
# Manual summary trigger endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/notifications/daily-summary")
def trigger_daily_summary(db: Session = Depends(get_db)):
    """Manually trigger the daily medication adherence summary for all caregivers."""
    notifier.send_daily_summary(db)
    return {"message": "Daily summary sent to all caregivers."}


@app.post("/api/notifications/weekly-summary")
def trigger_weekly_summary(db: Session = Depends(get_db)):
    """Manually trigger the weekly medication adherence summary for all caregivers."""
    notifier.send_weekly_summary(db)
    return {"message": "Weekly summary sent to all caregivers."}

# Real Prescription OCR & AI Parsing Endpoint using Gemini API
@app.post("/api/ocr-parser")
async def ocr_parser(file: UploadFile = File(...)):
    """
    Accepts an uploaded prescription image/PDF and uses Gemini Vision to extract medicines.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=400,
            detail="GEMINI_API_KEY is not configured. Please add GEMINI_API_KEY=your_key to your backend/.env file and restart the server."
        )

    try:
        # Read the uploaded file
        contents = await file.read()
        
        # Prepare the image structure for Gemini API
        image_parts = [
            {
                "mime_type": file.content_type,
                "data": contents
            }
        ]

        # Define prompt to extract structured JSON data matching our Medicine models
        prompt = """
        You are an expert medical assistant. Carefully analyze the uploaded prescription image or document.
        Your goal is to extract the list of medications with 100% accuracy, avoiding any discrepancies.

        CRITICAL INSTRUCTIONS:
        1. **Handwriting Analysis**: Carefully read the doctor's handwriting. If any medication name is ambiguous, cross-reference it with standard medical/drug databases to identify the correct spelling. If it remains completely illegible, prepend '[UNCLEAR]' to the name.
        2. **Timing & Multiple Doses**: 
           - Look for dosage frequencies like BD (twice daily), TDS (three times daily), QDS (four times daily), AM/PM, or morning/noon/night.
           - For medications taken multiple times a day, you MUST create a separate entry/object for each scheduled dose time.
           - Map them to specific 24-hour time format (HH:MM). Use reasonable defaults:
             * Morning / Breakfast / AM: "08:00"
             * Afternoon / Lunch / Noon: "13:00"
             * Evening / Tea: "17:00"
             * Night / Dinner / Bedtime / PM: "21:00"
           - For example, if a medicine is prescribed "twice daily", create one entry for "08:00" and another entry for "21:00".
        3. **Dosage & Duration**: Extract exactly what the doctor prescribed (e.g., "500mg (1 tablet)", "10ml", "1 drop"). Parse the duration (e.g., "7 Days", "1 Month", "30 Days"). If duration is not specified, default to "30 Days".
        4. **Elderly-Friendly Description**: Provide a very short description focusing ONLY on shape, size, colour, and smell (if applicable) to help the elderly patient identify it. Keep it extremely brief (e.g., "Small round white pill", "Large red capsule", "Pink liquid syrup"). Do not include long instructions or general tips like "take after food".

        Each medication in the list must have the following fields:
        - name: The name of the medicine (e.g. "Metformin")
        - dosage: The dosage strength and quantity (e.g. "500mg (1 tablet)" or "1 pill")
        - frequency: How often to take it (e.g. "Daily", "Twice daily", "Three times a day")
        - time: The specific time to take it in 24-hour HH:MM format (e.g. "08:00").
        - duration: The duration of the course (e.g. "30 Days").
        - description: Very short description of shape, size, colour, and smell only.

        Return ONLY a JSON object with a single top-level key "medicines", which points to an array of medication objects. Do not include markdown code block formatting or anything else.
        Example output format:
        {
          "medicines": [
            {
              "name": "Metformin",
              "dosage": "500mg (1 tablet)",
              "frequency": "Twice daily",
              "time": "08:00",
              "duration": "90 Days",
              "description": "Small pink oval tablet"
            }
          ]
        }
        """

        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(
            [prompt, image_parts[0]],
            generation_config={"response_mime_type": "application/json"}
        )
        
        text = response.text.strip()
        result = json.loads(text)
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from Gemini response: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to parse prescription. The model output was not valid JSON."
        )
    except Exception as e:
        logger.error(f"Error during Gemini OCR prescription parsing: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error parsing prescription: {str(e)}"
        )

