# app/models/db.py - Database connection infrastructure + re-exports
#
# This file owns: connection pool, get_db, close_db, init_db,
#                 upsert_profile_cv_extract, summarize_two_sentences,
#                 parse_job_description.
#
# Shared taxonomy and utility helpers live in:
#   models/taxonomy.py     — canonical categorize_function
#   models/utils.py        — now_iso, safe_salary_context
#
# All model logic has been split into focused modules:
#   models/jobs.py         — Job class, job summary cache, date/text helpers
#   models/money.py        — salary, compensation, analytics
#   models/identity.py     — subscribers, Stripe orders, subscriptions, API keys
#
# Re-exports from those modules are at the bottom of this file so that
# all existing `from .models.db import X` calls in app.py continue to work.

import json
import re
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import psycopg  # psycopg v3
except Exception:
    psycopg = None  # optional, only required when SUPABASE_URL is set

try:
    from psycopg.errors import UniqueViolation  # type: ignore[attr-defined]
except Exception:
    UniqueViolation = None  # type: ignore[assignment]

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# ----------------------------- Config ----------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

from ..settings import DB_POOL_MAX, SECRET_KEY, SUPABASE_URL  # noqa: E402

# ----------------------------- Logging ---------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("catalitium")

# ----------------------------- Connection Pool --------------------------------
_PG_POOL = None


def _setup_connection(conn):
    """Apply session settings and ensure autocommit."""
    try:
        conn.autocommit = True
    except Exception:
        pass
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout TO 8000")
            cur.execute("SET idle_in_transaction_session_timeout TO 5000")
            cur.execute("SET application_name TO 'catalitium'")
    except Exception:
        pass


def _init_pg_pool():
    """Initialize a small connection pool when psycopg_pool is available."""
    global _PG_POOL
    if _PG_POOL is not None or not SUPABASE_URL:
        return
    try:
        from psycopg_pool import ConnectionPool  # type: ignore
    except Exception:
        _PG_POOL = None
        return
    try:
        _PG_POOL = ConnectionPool(
            conninfo=SUPABASE_URL,
            min_size=1,
            max_size=max(1, DB_POOL_MAX),
            timeout=5,
        )
    except Exception as exc:
        logger.warning("ConnectionPool init failed, falling back to direct connects: %s", exc)
        _PG_POOL = None


def _acquire_connection():
    """Get a connection from the pool or open a new one."""
    global _PG_POOL
    if _PG_POOL is None:
        _init_pg_pool()
    if _PG_POOL is not None:
        try:
            conn = _PG_POOL.getconn(timeout=5)
            _setup_connection(conn)
            try:
                setattr(conn, "_from_pg_pool", True)
            except Exception:
                pass
            return conn
        except Exception as exc:
            logger.warning("Pool connection failed, retrying direct connect: %s", exc)
            _PG_POOL = None
    import psycopg
    conn = psycopg.connect(SUPABASE_URL, autocommit=True)
    _setup_connection(conn)
    try:
        setattr(conn, "_from_pg_pool", False)
    except Exception:
        pass
    return conn


def _pg_connect():
    """Connect to PostgreSQL database."""
    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL not set")
    return _acquire_connection()


def get_db():
    """Get database connection from Flask g object."""
    from flask import g

    if "db" not in g:
        try:
            g.db = _pg_connect()
        except Exception as e:
            logger.error("Postgres connection failed: %s", e)
            raise
    return g.db


def close_db(_e=None):
    """Close database connection."""
    from flask import g
    db = g.pop("db", None)
    if db:
        try:
            if getattr(db, "_from_pg_pool", False) and _PG_POOL is not None:
                _PG_POOL.putconn(db)
            else:
                db.close()
        except Exception:
            try:
                db.close()
            except Exception:
                pass


def _is_unique_violation(exc: Exception) -> bool:
    if UniqueViolation is not None and isinstance(exc, UniqueViolation):
        return True
    return False


def upsert_profile_cv_extract(
    user_id: str,
    cv_text: str,
    meta: Optional[Dict[str, Any]] = None,
    *,
    email: Optional[str] = None,
) -> str:
    """Insert or update ``profiles`` with parsed CV (handles missing profile row). Returns ``ok`` or ``error``."""
    uid = (user_id or "").strip()
    if not uid or not SUPABASE_URL:
        return "error"
    email_val = (email or "").strip() or None
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO profiles (id, email, cv_extracted_text, cv_meta, cv_extracted_at, updated_at)
                VALUES (%s::uuid, %s, %s, %s::jsonb, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    cv_extracted_text = EXCLUDED.cv_extracted_text,
                    cv_meta = EXCLUDED.cv_meta,
                    cv_extracted_at = EXCLUDED.cv_extracted_at,
                    updated_at = NOW()
                """,
                (uid, email_val, cv_text, json.dumps(meta or {})),
            )
        return "ok"
    except Exception as exc:
        logger.warning("upsert_profile_cv_extract failed: %s", exc, exc_info=True)
        return "error"


# ----------------------------- Schema Init -----------------------------------

def init_db():
    """Connectivity check + ensure all required tables and columns exist."""
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS job_summaries (
                    job_id     INTEGER PRIMARY KEY,
                    bullets    JSONB    NOT NULL DEFAULT '[]'::jsonb,
                    skills     JSONB    NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id                       SERIAL PRIMARY KEY,
                    email                    TEXT NOT NULL,
                    key_hash                 TEXT NOT NULL UNIQUE,
                    key_prefix               TEXT NOT NULL,
                    tier                     TEXT NOT NULL DEFAULT 'free_pending',
                    is_active                BOOLEAN NOT NULL DEFAULT FALSE,
                    monthly_limit            INTEGER NOT NULL DEFAULT 100,
                    requests_this_month      INTEGER NOT NULL DEFAULT 0,
                    month_window             TEXT,
                    confirm_token            TEXT,
                    confirm_token_expires_at TIMESTAMPTZ,
                    created_from_ip          TEXT,
                    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_active_email
                    ON api_keys (email) WHERE is_active = TRUE
            """)
            cur.execute(
                "ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS search_salary_band TEXT"
            )
            cur.execute(
                "ALTER TABLE job_posting ADD COLUMN IF NOT EXISTS user_id TEXT"
            )
            cur.execute(
                "ALTER TABLE job_posting ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ"
            )
            cur.execute(
                "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS daily_limit INT DEFAULT 50"
            )
            cur.execute(
                "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS requests_today INT DEFAULT 0"
            )
            cur.execute(
                "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS day_window TEXT DEFAULT ''"
            )
            cur.execute(
                "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS user_id TEXT"
            )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS salary_submissions (
                    id          SERIAL PRIMARY KEY,
                    job_title   TEXT NOT NULL,
                    company     TEXT,
                    location    TEXT NOT NULL,
                    seniority   TEXT NOT NULL,
                    base_salary INTEGER NOT NULL,
                    currency    TEXT NOT NULL DEFAULT 'CHF',
                    years_exp   INTEGER,
                    email       TEXT,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_title_norm ON jobs(job_title_norm)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_date ON jobs(date DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_location ON jobs(LOWER(location))"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_company_name ON jobs(LOWER(company_name))"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_salary_city ON salary(LOWER(city))"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_salary_region ON salary(LOWER(region))"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_salary_country ON salary(LOWER(country))"
            )
            cur.execute(
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_salary INTEGER"
            )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stripe_orders (
                    id                    SERIAL PRIMARY KEY,
                    stripe_session_id     TEXT UNIQUE NOT NULL,
                    stripe_customer_id    TEXT,
                    stripe_subscription_id TEXT,
                    user_id               TEXT NOT NULL,
                    user_email            TEXT NOT NULL,
                    price_id              TEXT NOT NULL,
                    plan_key              TEXT NOT NULL,
                    plan_name             TEXT NOT NULL,
                    status                TEXT NOT NULL DEFAULT 'pending',
                    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    paid_at               TIMESTAMPTZ,
                    job_submitted_at      TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_subscriptions (
                    id                      SERIAL PRIMARY KEY,
                    user_id                 TEXT NOT NULL,
                    user_email              TEXT NOT NULL,
                    product_line            TEXT NOT NULL,
                    tier                    TEXT NOT NULL,
                    stripe_customer_id      TEXT,
                    stripe_subscription_id  TEXT UNIQUE,
                    stripe_price_id         TEXT,
                    status                  TEXT NOT NULL DEFAULT 'active',
                    current_period_end      TIMESTAMPTZ,
                    cancel_at_period_end    BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_user_subs_user_product
                ON user_subscriptions(user_id, product_line)
            """)
            cur.execute(
                "UPDATE api_keys SET monthly_limit = 500 "
                "WHERE monthly_limit = 100 AND tier IN ('free_pending', 'free')"
            )
            db.commit()
    except Exception as exc:
        logger.warning("init_db connectivity check failed: %s", exc)


# ----------------------------- Description Parsing ---------------------------

# Small multilingual stopword set to keep summarizer lightweight
_STOPWORDS = {
    # EN
    "a","about","above","after","again","against","all","am","an","and","any","are","as","at",
    "be","because","been","before","being","below","between","both","but","by","can","could",
    "did","do","does","doing","down","during","each","few","for","from","further","had","has",
    "have","having","he","her","here","hers","herself","him","himself","his","how","i","if","in",
    "into","is","it","its","itself","me","more","most","my","myself","no","nor","not","of","off",
    "on","once","only","or","other","our","ours","ourselves","out","over","own","same","she","should",
    "so","some","such","than","that","the","their","theirs","them","themselves","then","there","these",
    "they","this","those","through","to","too","under","until","up","very","was","we","were","what",
    "when","where","which","while","who","whom","why","with","you","your","yours","yourself","yourselves",
    # ES/FR minimal
    "de","la","el","en","y","los","las","que","es","un","una","con","por","para","le","et","Ã ",
    "les","des","est","pour","dans"
}


def summarize_two_sentences(text: str) -> str:
    """Extract two most representative sentences from text (pure stdlib)."""
    if not text:
        return ""
    s = text.strip()
    sentences = re.split(r"(?<=[.!?])\s+", s)
    if len(sentences) < 2:
        return s
    words = re.findall(r"\b\w+\b", s.lower())
    freqs = Counter(w for w in words if w not in _STOPWORDS)
    scores = {}
    for sent in sentences:
        tokens = re.findall(r"\b\w+\b", sent.lower())
        if not tokens:
            continue
        score = sum(freqs.get(w, 0) for w in tokens if w not in _STOPWORDS) / max(len(tokens), 1)
        scores[sent] = score
    top = sorted(scores.items(), key=lambda x: (-x[1], sentences.index(x[0])))[:2]
    final = sorted([t[0] for t in top], key=lambda x: sentences.index(x))
    return " ".join(final)


def parse_job_description(text: str) -> str:
    """Clean and summarize a raw job description to a short, readable preview."""
    from .jobs import clean_job_description_text
    t = clean_job_description_text(text or "")
    return summarize_two_sentences(t)


# ----------------------------- Normalization (re-export) ---------------------
# Single source of truth lives in app/normalization.py
from ..normalization import (  # noqa: E402
    COUNTRY_NORM,
    LOCATION_COUNTRY_HINTS,
    SWISS_LOCATION_TERMS,
    TITLE_SYNONYMS,
    normalize_country,
    normalize_title,
)

# ----------------------------- Model re-exports ------------------------------
# All imports from `from .models.db import X` in app.py continue to work.

from .jobs import Job, get_job_summary, save_job_summary, format_job_date_string, clean_job_description_text  # noqa: E402,F401
from .money import (  # noqa: E402,F401
    insert_salary_submission,
    get_salary_for_location,
    parse_money_numbers,
    parse_salary_query,
    _compact_salary_number,
    salary_range_around,
    parse_salary_range_string,
)
from .identity import (  # noqa: E402,F401
    insert_stripe_order,
    mark_stripe_order_paid,
    mark_stripe_order_job_submitted,
    get_stripe_order,
    upsert_user_subscription,
    get_user_subscriptions,
    get_subscription_by_stripe_id,
    create_api_key,
    get_api_key_by_email,
    confirm_api_key_by_token,
    revoke_api_key,
    check_and_increment_api_key,
    sync_api_key_quota_for_api_access,
    insert_subscriber,
    insert_contact,
    insert_job_posting,
    JOB_POSTING_ACTIVE_DAYS,
)
