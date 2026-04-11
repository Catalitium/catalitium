"""User-facing write operations: subscribers, contact form, job postings.

All SQL for the subscribers, contact_form, and job_posting tables lives here.
No SMTP code. No normalization logic. Import these from app.py or blueprints.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from .db import get_db, logger, _is_unique_violation
from .utils import now_iso as _now_iso

JOB_POSTING_ACTIVE_DAYS = 10  # listings expire after this many days


def insert_subscriber(
    email: str,
    search_title: str = "",
    search_country: str = "",
    search_salary_band: str = "",
) -> str:
    """Insert a subscriber record; return 'ok', 'duplicate', or 'error'."""
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO subscribers(email, created_at, search_title, search_country, search_salary_band)
                VALUES(%s, %s, %s, %s, %s)
                """,
                (email, _now_iso(), search_title or None, search_country or None, search_salary_band or None),
            )
        return "ok"
    except Exception as exc:
        if _is_unique_violation(exc):
            return "duplicate"
        logger.warning("insert_subscriber failed: %s", exc, exc_info=True)
        return "error"


def insert_contact(email: str, name_company: str, message: str) -> str:
    """Insert a contact form submission; return 'ok' or 'error'."""
    db = get_db()
    email_clean = (email or "").strip()
    name_clean = (name_company or "").strip()
    msg_clean = (message or "").strip()
    try:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO contact_form(email, name_company, message, created_at)
                VALUES(%s, %s, %s, %s)
                """,
                (email_clean, name_clean, msg_clean, _now_iso()),
            )
        return "ok"
    except Exception as exc:
        logger.warning("insert_contact failed: %s", exc, exc_info=True)
        return "error"


def insert_job_posting(
    *,
    contact_email: str,
    job_title: str,
    company: str,
    description: str,
    salary_range: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    """Insert a recruiter job posting; return 'ok' or 'error'.

    Listings are active for JOB_POSTING_ACTIVE_DAYS days from creation.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=JOB_POSTING_ACTIVE_DAYS)
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO job_posting(
                    contact_email, job_title, company, description,
                    salary_range, user_id, expires_at, created_at
                )
                VALUES(%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    (contact_email or "").strip(),
                    (job_title or "").strip(),
                    (company or "").strip(),
                    (description or "").strip(),
                    (salary_range or "").strip() or None,
                    user_id or None,
                    expires_at,
                    now,
                ),
            )
        return "ok"
    except Exception as exc:
        logger.warning("insert_job_posting failed: %s", exc, exc_info=True)
        return "error"
