"""Stripe order and job-posting model functions."""

from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from .db import get_db, logger


JOB_POSTING_ACTIVE_DAYS = 10


def insert_job_posting(
    *,
    contact_email: str,
    job_title: str,
    company: str,
    description: str,
    salary_range: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
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


def insert_stripe_order(
    *,
    stripe_session_id: str,
    user_id: str,
    user_email: str,
    price_id: str,
    plan_key: str,
    plan_name: str,
) -> str:
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stripe_orders
                    (stripe_session_id, user_id, user_email, price_id, plan_key, plan_name, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending', NOW())
                ON CONFLICT (stripe_session_id) DO NOTHING
                """,
                (stripe_session_id, user_id, user_email, price_id, plan_key, plan_name),
            )
        return "ok"
    except Exception as exc:
        logger.warning("insert_stripe_order failed: %s", exc, exc_info=True)
        return "error"


def mark_stripe_order_paid(
    *,
    stripe_session_id: str,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
) -> str:
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE stripe_orders
                SET status = 'paid',
                    stripe_customer_id = COALESCE(%s, stripe_customer_id),
                    stripe_subscription_id = COALESCE(%s, stripe_subscription_id),
                    paid_at = NOW()
                WHERE stripe_session_id = %s
                """,
                (stripe_customer_id, stripe_subscription_id, stripe_session_id),
            )
        return "ok"
    except Exception as exc:
        logger.warning("mark_stripe_order_paid failed: %s", exc, exc_info=True)
        return "error"


def mark_stripe_order_job_submitted(*, stripe_session_id: str) -> str:
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                "UPDATE stripe_orders SET job_submitted_at = NOW() WHERE stripe_session_id = %s",
                (stripe_session_id,),
            )
        return "ok"
    except Exception as exc:
        logger.warning("mark_stripe_order_job_submitted failed: %s", exc, exc_info=True)
        return "error"


def get_stripe_order(stripe_session_id: str) -> Optional[Dict]:
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT stripe_session_id, user_id, user_email, price_id,
                       plan_key, plan_name, status, paid_at, job_submitted_at
                FROM stripe_orders WHERE stripe_session_id = %s
                """,
                (stripe_session_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "stripe_session_id": row[0],
                    "user_id": row[1],
                    "user_email": row[2],
                    "price_id": row[3],
                    "plan_key": row[4],
                    "plan_name": row[5],
                    "status": row[6],
                    "paid_at": row[7],
                    "job_submitted_at": row[8],
                }
    except Exception as exc:
        logger.warning("get_stripe_order failed: %s", exc, exc_info=True)
    return None


__all__ = [
    "JOB_POSTING_ACTIVE_DAYS",
    "insert_job_posting",
    "insert_stripe_order",
    "mark_stripe_order_paid",
    "mark_stripe_order_job_submitted",
    "get_stripe_order",
]
