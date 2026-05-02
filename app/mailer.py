"""Outbound email — all SMTP dispatching lives here.

Sends plain-text emails only. Best-effort with 3-attempt linear-backoff
retry. Never raises; logs on final failure.

Usage:
    from app.mailer import send_subscribe_welcome
    send_subscribe_welcome(email, focus="Python engineer")
"""

from __future__ import annotations

import logging
import os
import smtplib
import time
from email.mime.text import MIMEText

logger = logging.getLogger("catalitium")


def _base_url() -> str:
    return os.getenv("BASE_URL", "https://catalitium.com").rstrip("/")


def _send_mail(to: str, subject: str, body: str) -> None:
    """Send a plain-text email via SMTP. Best-effort; retries 3x, logs on final failure, never raises."""
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    pw = os.getenv("SMTP_PASS", "").strip()
    frm = os.getenv("SMTP_FROM", "noreply@catalitium.com").strip()
    if not host:
        logger.warning("_send_mail: SMTP_HOST not configured, skipping email to %s", to)
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = frm
    msg["To"] = to
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            with smtplib.SMTP(host, port, timeout=10) as s:
                s.ehlo()
                s.starttls()
                s.ehlo()
                if user:
                    s.login(user, pw)
                s.send_message(msg)
            return  # success
        except Exception as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(2)
    logger.warning("_send_mail failed after 3 attempts (to=%s): %s", to, last_exc)


def send_subscribe_welcome(email: str, focus: str = "") -> None:
    """Send a welcome confirmation email to a new subscriber."""
    focus_line = f"\nYour focus: {focus}\n" if focus else ""
    body = f"""Welcome to Catalitium.

You're now on the weekly high-match digest.{focus_line}
Every week we send you the highest-signal tech jobs with real salary data: no noise, no spam.

Browse jobs now: {_base_url()}

--
Catalitium | info@catalitium.com
Unsubscribe: {_base_url()}/unsubscribe
"""
    _send_mail(email, "You're on the Catalitium weekly digest", body)


def send_api_key_activation(email: str, raw_key: str, confirm_url: str) -> None:
    """Send API key details to a new free-tier registrant (needs email confirmation)."""
    body = (
        f"Hello,\n\n"
        f"Your Catalitium API key is:\n\n"
        f"  {raw_key}\n\n"
        f"To activate it, visit the link below (valid 24 hours):\n\n"
        f"  {confirm_url}\n\n"
        f"Once activated, include it in API requests with the header:\n"
        f"  X-API-Key: {raw_key}\n\n"
        f"Free tier: 50 requests/day and 500 per calendar month after activation.\n\n"
        f"-- Catalitium Team"
    )
    _send_mail(email, "Activate your Catalitium API key", body)


def send_api_access_key_provisioned(email: str, raw_key: str, confirm_url: str) -> None:
    """Send API key details after an API Access subscription is activated via Stripe."""
    body = (
        "Your Catalitium API Access subscription is active.\n\n"
        f"Your API key:\n\n  {raw_key}\n\n"
        f"Activate it within 24 hours:\n\n  {confirm_url}\n\n"
        f"Then use header:\n  X-API-Key: {raw_key}\n\n"
        "Included: up to 10,000 successful API calls per calendar month.\n\n"
        "-- Catalitium Team\nhttps://catalitium.com"
    )
    _send_mail(email, "Catalitium API Access — your API key", body)


def send_api_access_payment_confirmed(email: str) -> None:
    """Send receipt to an existing key holder whose API Access subscription renewed."""
    body = (
        "Thanks — your API Access subscription payment was received.\n\n"
        "Your existing API key now includes the paid monthly quota "
        "(10,000 calls per month). Continue using the same key with "
        "header X-API-Key.\n\n"
        f"Manage your plan: {_base_url()}/account/subscription\n\n"
        "-- Catalitium Team"
    )
    _send_mail(email, "Catalitium — API Access payment confirmed", body)


def send_api_key_activation_reminder(email: str, confirm_url: str) -> None:
    """Remind a subscriber with a pending key to activate it after subscribing."""
    body = (
        "Your API Access subscription is active.\n\n"
        "Confirm the API key you registered earlier:\n\n"
        f"  {confirm_url}\n\n"
        "Then use header X-API-Key on /v1/* endpoints.\n\n"
        "-- Catalitium"
    )
    _send_mail(email, "Activate your Catalitium API key (API Access)", body)


def send_job_posting_admin_notification(
    admin_email: str,
    job_title: str,
    company: str,
    plan_name: str,
    user_email: str,
    session_id: str,
    location: str,
    salary_range: str,
    apply_url: str,
    description: str,
) -> None:
    """Notify the admin when a recruiter submits a paid job posting."""
    _send_mail(
        admin_email,
        f"[New Job Posting] {job_title} at {company} ({plan_name})",
        (
            f"Plan: {plan_name}\n"
            f"Paid by: {user_email}\n"
            f"Session: {session_id}\n\n"
            f"Title: {job_title}\n"
            f"Company: {company}\n"
            f"Location: {location or 'Not specified'}\n"
            f"Salary: {salary_range or 'Not specified'}\n"
            f"Apply URL: {apply_url or 'Not specified'}\n\n"
            f"Description:\n{description}"
        ),
    )


def send_job_posting_confirmation(
    user_email: str,
    job_title: str,
    company: str,
    plan_name: str,
) -> None:
    """Confirm to the recruiter that their job posting was received."""
    _send_mail(
        user_email,
        f"Job posting confirmed: {job_title} at {company}",
        (
            f"Hi,\n\nYour job posting has been received and will go live shortly.\n\n"
            f"Plan: {plan_name}\n"
            f"Job title: {job_title}\n"
            f"Company: {company}\n\n"
            f"We'll review and publish it within 24 hours.\n\n"
            f"Thanks,\nThe Catalitium Team\nhttps://catalitium.com"
        ),
    )


__all__ = [
    "send_subscribe_welcome",
    "send_api_key_activation",
    "send_api_access_key_provisioned",
    "send_api_access_payment_confirmed",
    "send_api_key_activation_reminder",
    "send_job_posting_admin_notification",
    "send_job_posting_confirmation",
]
