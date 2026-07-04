"""
twilio_service.py
Thin wrapper around the Twilio REST client.
All direct Twilio API calls go through this module so the rest of the
service layer stays unit-testable without real credentials.
"""

import logging
import os

logger = logging.getLogger("LastMileMeds.twilio_service")


def get_twilio_client():
    """Lazily return a Twilio Client, or None if credentials are missing."""
    from twilio.rest import Client
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if sid and token:
        try:
            return Client(sid, token)
        except Exception as e:
            logger.error(f"Failed to create Twilio client: {e}")
    return None


def make_voice_call(to: str, twiml_url: str, status_callback_url: str) -> str | None:
    """
    Place an outbound Twilio Voice call.

    Returns the Twilio Call SID on success, or None on failure / missing creds.
    """
    client = get_twilio_client()
    from_number = os.getenv("TWILIO_PHONE_NUMBER")

    if not client or not from_number:
        logger.info("Twilio credentials not configured — skipping real call (simulation mode).")
        return None

    try:
        call = client.calls.create(
            url=twiml_url,
            to=to,
            from_=from_number,
            status_callback=status_callback_url,
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
        logger.info(f"Twilio call created: SID={call.sid} → {to}")
        return call.sid
    except Exception as e:
        logger.error(f"Twilio make_voice_call failed: {e}")
        return None


def send_whatsapp(to: str, body: str) -> bool:
    """
    Send a WhatsApp message via Twilio.

    `to` should be a bare phone number (e.g. '+919876543210').
    The 'whatsapp:' prefix is added automatically.

    Returns True on success, False on failure / missing creds.
    """
    client = get_twilio_client()
    from_number = os.getenv("TWILIO_PHONE_NUMBER")

    if not client or not from_number:
        logger.info(f"Twilio not configured — WhatsApp simulation to {to}: {body[:80]}…")
        return False

    try:
        msg = client.messages.create(
            body=body,
            from_=f"whatsapp:{from_number}",
            to=f"whatsapp:{to}",
        )
        logger.info(f"WhatsApp sent: SID={msg.sid} → {to}")
        return True
    except Exception as e:
        logger.error(f"Twilio send_whatsapp failed to {to}: {e}")
        return False
