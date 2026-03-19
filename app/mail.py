"""Email sending utilities for Catalitium."""

import os
import smtplib
from email.mime.text import MIMEText
from typing import List, Optional

from .models.db import logger

# Read SMTP config once at import time — these values never change at runtime.
_SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER = os.getenv("SMTP_USER", "").strip()
_SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
_SMTP_FROM = os.getenv("SMTP_FROM", "noreply@catalitium.com").strip()


def send_mail(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email via SMTP. Returns True on success, False on failure."""
    host = _SMTP_HOST
    if not host:
        logger.warning("send_mail: SMTP_HOST not configured, skipping email to %s", to)
        return False
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = _SMTP_FROM
        msg["To"] = to
        with smtplib.SMTP(host, _SMTP_PORT, timeout=10) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            if _SMTP_USER:
                s.login(_SMTP_USER, _SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as exc:
        logger.warning("send_mail failed (to=%s): %s", to, exc)
        return False


def _send_alert_email(subscriber: dict, jobs: List[dict], base_url: str = "https://catalitium.com") -> bool:
    """Send a job alert digest email to a subscriber.

    subscriber dict must have 'email', optionally 'search_title', 'search_country'.
    jobs is a list of job dicts with at least 'job_title' and 'company_name'.
    base_url is the site root (e.g. request.host_url.rstrip('/')) so staging envs
    don't send emails pointing at the production domain.
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
        f"View all matching jobs at: {base_url}",
        "",
        "-- Catalitium Team",
        f"Unsubscribe: reply with 'unsubscribe' or visit {base_url}/legal",
    ]

    body = "\n".join(lines)
    subject = f"Your weekly job digest: {focus_label}"
    return send_mail(email, subject, body)
