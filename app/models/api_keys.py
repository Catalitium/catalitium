"""API key model functions."""

from datetime import datetime
from typing import Dict, Optional

from .db import get_db, logger


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


__all__ = [
    "create_api_key",
    "get_api_key_by_email",
    "confirm_api_key_by_token",
    "revoke_api_key",
    "check_and_increment_api_key",
    "sync_api_key_quota_for_api_access",
]
