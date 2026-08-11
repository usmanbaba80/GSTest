"""Transactional email sending via Brevo (free tier suitable for OTP)."""

from typing import Optional

import httpx

from config import settings
from logger import logger

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


def is_email_configured() -> bool:
    return bool(settings.brevo_api_key and settings.brevo_sender_email)


async def send_otp_email(to_email: str, otp_code: str, full_name: Optional[str] = None) -> None:
    """
    Send a signup verification OTP email.

    Uses Brevo Transactional API (free plan is enough for OTP volume).
    If Brevo is not configured and email_otp_debug=True, logs the OTP instead.
    """
    display_name = (full_name or "there").strip() or "there"
    subject = "Your verification code"
    text_content = (
        f"Hi {display_name},\n\n"
        f"Your verification code is: {otp_code}\n\n"
        f"This code expires in {settings.otp_expire_minutes} minutes.\n"
        f"If you did not sign up, you can ignore this email.\n"
    )
    html_content = f"""
    <p>Hi {display_name},</p>
    <p>Your verification code is:</p>
    <p style="font-size:24px;font-weight:700;letter-spacing:4px;">{otp_code}</p>
    <p>This code expires in {settings.otp_expire_minutes} minutes.</p>
    <p>If you did not sign up, you can ignore this email.</p>
    """

    if not is_email_configured():
        if settings.email_otp_debug:
            logger.warning(
                f"[EMAIL_OTP_DEBUG] OTP for {to_email}: {otp_code} "
                "(Brevo not configured — enable BREVO_API_KEY for production)"
            )
            return
        raise RuntimeError(
            "Email provider is not configured. Set BREVO_API_KEY and BREVO_SENDER_EMAIL in .env"
        )

    payload = {
        "sender": {
            "name": settings.brevo_sender_name,
            "email": settings.brevo_sender_email,
        },
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
        "textContent": text_content,
    }

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": settings.brevo_api_key,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(BREVO_SEND_URL, json=payload, headers=headers)
        if response.status_code >= 400:
            logger.error(f"Brevo send failed ({response.status_code}): {response.text}")
            response.raise_for_status()

    logger.info(f"Verification OTP emailed to {to_email}")
