"""FastAPI route for Twilio WhatsApp webhooks.

Security
--------
Every inbound request is validated against the Twilio signature header
(``X-Twilio-Signature``) to prevent spoofing. Validation is skipped in
debug mode to ease local development with ngrok.

Flow
----
1. Twilio sends a POST with form-encoded fields.
2. We validate the signature, then dispatch processing as a BackgroundTask.
3. We immediately return HTTP 200 / empty TwiML so Twilio does not retry.
4. The background task runs ``handle_message`` and sends the reply via the
   Twilio client (not via TwiML), which also supports fire-and-forget
   sub-tasks (e.g. long-running analysis).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request, Response
from twilio.request_validator import RequestValidator

from app.config import settings
from app.handlers.command_handler import handle_message
from app.services.whatsapp import async_send_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["webhook"])

# Minimal TwiML that tells Twilio "message received, no auto-reply needed"
_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


# ---------------------------------------------------------------------------
# Signature validation
# ---------------------------------------------------------------------------


def _twilio_signature_valid(request: Request, form_data: dict) -> bool:
    validator = RequestValidator(settings.twilio_auth_token)
    signature = request.headers.get("X-Twilio-Signature", "")
    return validator.validate(str(request.url), form_data, signature)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/webhook/whatsapp", response_class=Response)
async def whatsapp_webhook(
    background_tasks: BackgroundTasks,
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
    MessageSid: str = Form(default=""),
    To: str = Form(default=""),
) -> Response:
    """Receive inbound WhatsApp messages from Twilio."""
    form_data = dict(await request.form())

    if not settings.debug and not _twilio_signature_valid(request, form_data):
        logger.warning("Invalid Twilio signature from %s [%s]", From, MessageSid)
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    logger.info("Inbound WhatsApp from=%s sid=%s body=%r", From, MessageSid, Body[:80])

    # Dispatch async processing; return immediately so Twilio does not retry
    background_tasks.add_task(_process_and_reply, From, Body)

    return Response(content=_EMPTY_TWIML, media_type="application/xml")


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------


async def _process_and_reply(from_number: str, body: str) -> None:
    """Handle a command and send the response back via the Twilio client."""
    try:
        response_text = await handle_message(from_number, body)
        if response_text:
            await async_send_message(from_number, response_text)
    except Exception:
        logger.exception("Unhandled error processing message from %s", from_number)
        # Best-effort error notification to the user
        try:
            await async_send_message(
                from_number,
                "⚠️ An internal error occurred. Please try again later.",
            )
        except Exception:
            pass
