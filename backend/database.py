import datetime
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Load dotenv to read DATABASE_URL if present
load_dotenv()

DEFAULT_DATABASE_URL = "postgresql://postgres.kmsouchccobpipcmwldx:rvce%23_50lpa@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class CallStatus:
    """String enum for call/reminder job state transitions."""
    SCHEDULED = "SCHEDULED"
    CALLING = "CALLING"
    ANSWERED = "ANSWERED"
    NO_ANSWER = "NO_ANSWER"
    BUSY = "BUSY"
    FAILED = "FAILED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    UNCONFIRMED = "UNCONFIRMED"
    CAREGIVER_NOTIFIED = "CAREGIVER_NOTIFIED"
    # Legacy / scheduler aliases
    PENDING = "PENDING"
    RETRYING = "RETRYING"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    role = Column(String, default="caregiver")  # caregiver


class Elderly(Base):
    __tablename__ = "elderly"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    phone = Column(String)
    language = Column(String, default="English")  # English, Hindi, Kannada, etc.
    caregiver_id = Column(Integer, ForeignKey("users.id"))
    caregiver_whatsapp = Column(String)
    greeting_audio_url = Column(String, nullable=True)  # custom recorded audio message if any

    medicines = relationship("Medicine", back_populates="elderly", cascade="all, delete-orphan")
    reminder_jobs = relationship("ReminderJob", back_populates="elderly", cascade="all, delete-orphan")


class Medicine(Base):
    __tablename__ = "medicines"
    id = Column(Integer, primary_key=True, index=True)
    elderly_id = Column(Integer, ForeignKey("elderly.id"))
    name = Column(String, index=True)
    dosage = Column(String)       # e.g., "1 pill"
    frequency = Column(String)    # e.g., "Daily"
    time = Column(String)         # e.g., "08:00"
    duration = Column(String)     # e.g., "30 Days"
    description = Column(String)  # plain-language e.g., "small white round tablet"
    # Caregiver-defined recognition cue used in WhatsApp notifications.
    # e.g. "yellow capsule in compartment two" or "blue strip with red line".
    # Falls back to description if not set.
    medicine_cue = Column(String, nullable=True)

    elderly = relationship("Elderly", back_populates="medicines")
    reminder_jobs = relationship("ReminderJob", back_populates="medicine", cascade="all, delete-orphan")


class ReminderJob(Base):
    __tablename__ = "reminder_jobs"
    id = Column(Integer, primary_key=True, index=True)
    elderly_id = Column(Integer, ForeignKey("elderly.id"))
    medicine_id = Column(Integer, ForeignKey("medicines.id"))
    scheduled_time = Column(DateTime, index=True)

    # Status follows CallStatus transitions
    status = Column(String, default=CallStatus.PENDING)
    attempt_count = Column(Integer, default=0)
    last_attempt_time = Column(DateTime, nullable=True)
    failure_reason = Column(String, nullable=True)

    # Twilio call tracking
    call_sid = Column(String, nullable=True)          # Twilio Call SID of latest call
    last_call_status = Column(String, nullable=True)  # e.g. ANSWERED, NO_ANSWER, BUSY, FAILED

    # Confirmation tracking
    confirmation_status = Column(String, default="PENDING")  # PENDING | CONFIRMED | UNCONFIRMED
    confirmation_timestamp = Column(DateTime, nullable=True)

    # Caregiver notification tracking
    caregiver_notified = Column(Boolean, default=False)

    elderly = relationship("Elderly", back_populates="reminder_jobs")
    medicine = relationship("Medicine", back_populates="reminder_jobs")
    call_logs = relationship("CallLog", back_populates="reminder_job", cascade="all, delete-orphan")


class CallLog(Base):
    __tablename__ = "call_logs"
    id = Column(Integer, primary_key=True, index=True)
    reminder_job_id = Column(Integer, ForeignKey("reminder_jobs.id"))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    attempt_num = Column(Integer)
    status = Column(String)              # ANSWERED, NO_ANSWER, BUSY, FAILED, CONFIRMED
    confirmed = Column(Boolean, default=False)
    details = Column(String, nullable=True)
    # Twilio Call SID for cross-referencing with Twilio console
    call_sid = Column(String, nullable=True)

    reminder_job = relationship("ReminderJob", back_populates="call_logs")


def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # Create a default user if not exists
    if not db.query(User).first():
        default_user = User(username="caregiver_karthik", email="karthik@example.com", role="caregiver")
        db.add(default_user)
        db.commit()
    db.close()
