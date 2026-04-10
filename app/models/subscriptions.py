"""Stripe orders and B2C user subscriptions.

All SQL for the stripe_orders and user_subscriptions tables lives here.
No Stripe SDK calls — that stays in app.py route handlers.
"""

from typing import Dict, Optional

from .db import get_db, logger


def insert_stripe_order(
    *,
    stripe_session_id: str,
    user_id: str,
    user_email: str,
    price_id: str,
    plan_key: str,
    plan_name: str,
) -> str:
    """Insert a pending stripe order; return 'ok' or 'error'."""
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
    """Mark a stripe order as paid; return 'ok' or 'error'."""
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
    """Mark a stripe order as having a job submitted; return 'ok' or 'error'."""
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
    """Return stripe order dict or None."""
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


def upsert_user_subscription(
    *,
    user_id: str,
    user_email: str,
    product_line: str,
    tier: str,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    stripe_price_id: Optional[str] = None,
    status: str = "active",
    current_period_end: Optional[int] = None,
    cancel_at_period_end: bool = False,
) -> str:
    """Upsert a B2C subscription row; return 'ok' or 'error'."""
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_subscriptions
                    (user_id, user_email, product_line, tier,
                     stripe_customer_id, stripe_subscription_id, stripe_price_id,
                     status, current_period_end, cancel_at_period_end,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                        to_timestamp(%s), %s, NOW(), NOW())
                ON CONFLICT (user_id, product_line) DO UPDATE SET
                    tier                   = EXCLUDED.tier,
                    stripe_customer_id     = COALESCE(EXCLUDED.stripe_customer_id,     user_subscriptions.stripe_customer_id),
                    stripe_subscription_id = COALESCE(EXCLUDED.stripe_subscription_id, user_subscriptions.stripe_subscription_id),
                    stripe_price_id        = COALESCE(EXCLUDED.stripe_price_id,        user_subscriptions.stripe_price_id),
                    status                 = EXCLUDED.status,
                    current_period_end     = COALESCE(EXCLUDED.current_period_end,     user_subscriptions.current_period_end),
                    cancel_at_period_end   = EXCLUDED.cancel_at_period_end,
                    updated_at             = NOW()
                """,
                (
                    user_id, user_email, product_line, tier,
                    stripe_customer_id, stripe_subscription_id, stripe_price_id,
                    status, current_period_end, cancel_at_period_end,
                ),
            )
        return "ok"
    except Exception as exc:
        logger.warning("upsert_user_subscription failed: %s", exc, exc_info=True)
        return "error"


def get_user_subscriptions(user_id: str) -> Dict[str, Dict]:
    """Return {product_line: subscription_dict} for a user (all statuses)."""
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, user_email, product_line, tier,
                       stripe_customer_id, stripe_subscription_id, stripe_price_id,
                       status, current_period_end, cancel_at_period_end
                FROM user_subscriptions WHERE user_id = %s
                """,
                (user_id,),
            )
            result: Dict[str, Dict] = {}
            for row in cur.fetchall():
                pl = row[2]
                result[pl] = {
                    "user_id": row[0],
                    "user_email": row[1],
                    "product_line": pl,
                    "tier": row[3],
                    "stripe_customer_id": row[4],
                    "stripe_subscription_id": row[5],
                    "stripe_price_id": row[6],
                    "status": row[7],
                    "current_period_end": row[8],
                    "cancel_at_period_end": bool(row[9]),
                }
            return result
    except Exception as exc:
        logger.warning("get_user_subscriptions failed: %s", exc, exc_info=True)
        return {}


def get_subscription_by_stripe_id(stripe_subscription_id: str) -> Optional[Dict]:
    """Return subscription dict by stripe_subscription_id, or None."""
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, user_email, product_line, tier,
                       stripe_customer_id, stripe_subscription_id, stripe_price_id,
                       status, current_period_end, cancel_at_period_end
                FROM user_subscriptions WHERE stripe_subscription_id = %s
                """,
                (stripe_subscription_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "user_id": row[0],
                    "user_email": row[1],
                    "product_line": row[2],
                    "tier": row[3],
                    "stripe_customer_id": row[4],
                    "stripe_subscription_id": row[5],
                    "stripe_price_id": row[6],
                    "status": row[7],
                    "current_period_end": row[8],
                    "cancel_at_period_end": bool(row[9]),
                }
    except Exception as exc:
        logger.warning("get_subscription_by_stripe_id failed: %s", exc, exc_info=True)
    return None
