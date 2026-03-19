"""Email sending utilities for Catalitium."""

import os
import smtplib
from email.mime.text import MIMEText
from typing import List

from .models.db import logger


def send_mail(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email via SMTP. Returns True on success, False on failure."""
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    pw = os.getenv("SMTP_PASS", "").strip()
    frm = os.getenv("SMTP_FROM", "noreply@catalitium.com").strip()
    if not host:
        logger.warning("send_mail: SMTP_HOST not configured, skipping email to %s", to)
        return False
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = frm
        msg["To"] = to
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            if user:
                s.login(user, pw)
            s.send_message(msg)
        return True
    except Exception as exc:
        logger.warning("send_mail failed (to=%s): %s", to, exc)
        return False


def _send_alert_email(subscriber: dict, jobs: List[dict]) -> bool:
    """Send a job alert digest email to a subscriber.

    subscriber dict must have 'email', optionally 'search_title', 'search_country'.
    jobs is a list of job dicts with at least 'job_title' and 'company_name'.
    Returns True on success, False on failure.
    """
    email = subscriber.get("email", "")
    search_title = subscriber.get("search_title") or ""
    search_country = subscriber.get("search_country") or ""

    if not email:
        return False

    focus_parts = [p for p in [search_title, search_country] if p]
    focus_label = " / ".join(focus_parts) if focus_parts else "all tech roles"

    lines = [
        "Hi,",
        "",
        f"Here are this week's top matches for: {focus_label}",
        "",
    ]
    for i, job in enumerate(jobs[:10], 1):
        title = (job.get("job_title") or job.get("title") or "").strip()
        company = (job.get("company_name") or job.get("company") or "").strip()
        location = (job.get("location") or "").strip()
        lines.append(f"{i}. {title} at {company}" + (f" ({location})" if location else ""))

    lines += [
        "",
        "View all matching jobs at: https://catalitium.com",
        "",
        "-- Catalitium Team",
        "Unsubscribe: reply with 'unsubscribe' or visit catalitium.com/legal",
    ]

    body = "\n".join(lines)
    subject = f"Your weekly job digest: {focus_label}"
    return send_mail(email, subject, body)
