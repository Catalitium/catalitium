"""User subscription model functions."""

from typing import Dict, Optional

from .db import get_db, logger


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


__all__ = [
    "upsert_user_subscription",
    "get_user_subscriptions",
    "get_subscription_by_stripe_id",
]
