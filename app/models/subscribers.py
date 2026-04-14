"""Subscriber and contact-form model functions."""

from .db import get_db, logger, _is_unique_violation
from ..utils import now_iso as _now_iso


def insert_subscriber(
    email: str,
    search_title: str = "",
    search_country: str = "",
    search_salary_band: str = "",
) -> str:
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


__all__ = ["insert_subscriber", "insert_contact"]
