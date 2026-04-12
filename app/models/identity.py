"""Subscribers, contacts, job postings, Stripe orders, subscriptions, and API keys."""

from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from .db import get_db, logger, _is_unique_violation


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


JOB_POSTING_ACTIVE_DAYS = 10


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


def create_api_key(
    email: str,
    key_hash: str,
    key_prefix: str,
    confirm_token: str,
    confirm_token_expires_at: datetime,
    created_from_ip: Optional[str],
    user_id: Optional[str] = None,
) -> bool:
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_keys (
                    email, key_hash, key_prefix, tier, is_active,
                    monthly_limit, requests_this_month,
                    daily_limit, requests_today, day_window,
                    user_id, confirm_token, confirm_token_expires_at, created_from_ip, created_at
                ) VALUES (%s, %s, %s, 'free_pending', FALSE, 500, 0, 50, 0, '', %s, %s, %s, %s, NOW())
                """,
                (email, key_hash, key_prefix, user_id, confirm_token, confirm_token_expires_at, created_from_ip),
            )
        return True
    except Exception as exc:
        logger.warning("create_api_key failed: %s", exc, exc_info=True)
        return False


def get_api_key_by_email(email: str) -> Optional[Dict]:
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT id, email, key_prefix, tier, is_active, monthly_limit,
                       requests_this_month, month_window,
                       daily_limit, requests_today, day_window, user_id,
                       confirm_token, confirm_token_expires_at, created_from_ip, created_at
                FROM api_keys
                WHERE email = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (email,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [
                "id", "email", "key_prefix", "tier", "is_active", "monthly_limit",
                "requests_this_month", "month_window",
                "daily_limit", "requests_today", "day_window", "user_id",
                "confirm_token", "confirm_token_expires_at", "created_from_ip", "created_at",
            ]
            return dict(zip(cols, row))
    except Exception as exc:
        logger.warning("get_api_key_by_email failed: %s", exc)
        return None


def confirm_api_key_by_token(token: str, now: datetime) -> bool:
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE api_keys AS k
                SET is_active = TRUE,
                    tier = CASE
                        WHEN EXISTS (
                            SELECT 1 FROM user_subscriptions u
                            WHERE LOWER(TRIM(u.user_email)) = LOWER(TRIM(k.email))
                              AND u.product_line = 'api_access'
                              AND u.status = 'active'
                        ) THEN 'api_access'
                        ELSE 'free'
                    END,
                    confirm_token = NULL,
                    confirm_token_expires_at = NULL
                WHERE k.confirm_token = %s
                  AND k.confirm_token_expires_at > %s
                  AND k.is_active = FALSE
                """,
                (token, now),
            )
            return cur.rowcount > 0
    except Exception as exc:
        logger.warning("confirm_api_key_by_token failed: %s", exc)
        return False


def revoke_api_key(key_hash: str) -> bool:
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                "UPDATE api_keys SET is_active = FALSE WHERE key_hash = %s AND is_active = TRUE",
                (key_hash,),
            )
            return cur.rowcount > 0
    except Exception as exc:
        logger.warning("revoke_api_key failed: %s", exc)
        return False


def check_and_increment_api_key(key_hash: str, now: datetime) -> Optional[Dict]:
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT id, tier, is_active,
                       daily_limit, requests_today, day_window,
                       monthly_limit, requests_this_month, month_window
                FROM api_keys
                WHERE key_hash = %s
                """,
                (key_hash,),
            )
            row = cur.fetchone()
            if not row:
                return None
            (
                rec_id,
                tier,
                is_active,
                daily_limit,
                requests_today,
                day_window,
                monthly_limit,
                requests_this_month,
                month_window,
            ) = row
            if not is_active:
                return None
            if daily_limit is None:
                daily_limit = 50
            if monthly_limit is None:
                monthly_limit = 500

            today = now.strftime("%Y-%m-%d")
            month = now.strftime("%Y-%m")

            if (month_window or "") != month:
                cur.execute(
                    "UPDATE api_keys SET requests_this_month = 0, month_window = %s WHERE id = %s",
                    (month, rec_id),
                )
                requests_this_month = 0
            if requests_this_month >= monthly_limit:
                return {"error": "quota_exceeded", "window": "monthly"}

            if day_window != today:
                cur.execute(
                    "UPDATE api_keys SET requests_today = 0, day_window = %s WHERE id = %s",
                    (today, rec_id),
                )
                requests_today = 0
            if requests_today >= daily_limit:
                return {"error": "quota_exceeded", "window": "daily"}

            cur.execute(
                """
                UPDATE api_keys
                SET requests_today = requests_today + 1,
                    requests_this_month = requests_this_month + 1
                WHERE id = %s
                RETURNING requests_today, requests_this_month
                """,
                (rec_id,),
            )
            new_row = cur.fetchone()
            new_daily = new_row[0] if new_row else requests_today + 1
            new_monthly = new_row[1] if new_row else requests_this_month + 1
            return {
                "daily_limit": daily_limit,
                "requests_today": new_daily,
                "monthly_limit": monthly_limit,
                "requests_this_month": new_monthly,
                "tier": tier,
            }
    except Exception as exc:
        logger.warning("check_and_increment_api_key error: %s", exc)
        return None


def sync_api_key_quota_for_api_access(email: str, paid_active: bool) -> bool:
    email_clean = (email or "").strip()
    if not email_clean:
        return False
    try:
        db = get_db()
        with db.cursor() as cur:
            if paid_active:
                cur.execute(
                    """
                    UPDATE api_keys
                    SET monthly_limit = 10000,
                        daily_limit = 10000,
                        tier = 'api_access'
                    WHERE LOWER(TRIM(email)) = LOWER(TRIM(%s))
                    """,
                    (email_clean,),
                )
            else:
                cur.execute(
                    """
                    UPDATE api_keys
                    SET monthly_limit = 500,
                        daily_limit = 50,
                        tier = 'free'
                    WHERE LOWER(TRIM(email)) = LOWER(TRIM(%s))
                    """,
                    (email_clean,),
                )
        return True
    except Exception as exc:
        logger.warning("sync_api_key_quota_for_api_access error: %s", exc)
        return False
