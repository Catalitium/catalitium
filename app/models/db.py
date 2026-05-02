# app/models/db.py - Database connection infrastructure
#
# This file owns: connection pool, get_db, close_db, init_db,
#                 upsert_profile_cv_extract, summarize_two_sentences,
#                 parse_job_description, SECRET_KEY/SUPABASE_URL passthrough.
#
# Domain models: import from ``catalog``, ``money``, ``identity``, or ``utils`` directly.

import json
import re
import logging
from collections import Counter
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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

from ..config import DB_POOL_MAX, SECRET_KEY, SUPABASE_URL  # noqa: E402

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
            open=True,
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
    analysis_full: Optional[Dict[str, Any]] = None,
    cv_url: Optional[str] = None,
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
                INSERT INTO profiles (
                    id, email, cv_extracted_text, cv_meta, cv_extracted_at, updated_at,
                    cv_analysis_full, cv_url
                )
                VALUES (
                    %s::uuid, %s, %s, %s::jsonb, NOW(), NOW(),
                    %s::jsonb, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    cv_extracted_text = EXCLUDED.cv_extracted_text,
                    cv_meta = EXCLUDED.cv_meta,
                    cv_extracted_at = EXCLUDED.cv_extracted_at,
                    cv_analysis_full = EXCLUDED.cv_analysis_full,
                    cv_url = EXCLUDED.cv_url,
                    updated_at = NOW()
                """,
                (
                    uid, email_val, cv_text, json.dumps(meta or {}),
                    json.dumps(analysis_full or {}), cv_url
                ),
            )
        return "ok"
    except Exception as exc:
        logger.warning("upsert_profile_cv_extract failed: %s", exc, exc_info=True)
        return "error"


def insert_cv_upload_row(
    session_token: str,
    cv_text: str,
    cv_meta: Optional[Dict[str, Any]] = None,
    *,
    user_id: Optional[str] = None,
    storage_path: Optional[str] = None,
    cv_analysis_full: Optional[Dict[str, Any]] = None,
    inferred_title: Optional[str] = None,
    inferred_seniority: Optional[str] = None,
    top_skills: Optional[List[str]] = None,
    industry_bucket: Optional[str] = None,
    inferred_country: Optional[str] = None,
    source: str = "carl_individual",
    consent_note: Optional[str] = None,
) -> str:
    """Persist a Carl CV upload row (anonymous or authenticated). Returns ``ok`` / ``skipped`` / ``error``."""
    tok = (session_token or "").strip()
    text = (cv_text or "").strip()
    if not tok or not text or not SUPABASE_URL:
        return "skipped"
    uid = (user_id or "").strip() or None
    expires_at: Optional[datetime] = None
    if not uid:
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cv_uploads (
                    session_token, user_id, storage_path,
                    cv_extracted_text, cv_analysis_full, cv_meta,
                    inferred_title, inferred_seniority, top_skills,
                    industry_bucket, inferred_country,
                    source, consent_note, expires_at
                )
                VALUES (
                    %s, %s::uuid, %s,
                    %s, %s::jsonb, %s::jsonb,
                    %s, %s, %s::jsonb,
                    %s, %s,
                    %s, %s, %s
                )
                """,
                (
                    tok,
                    uid,
                    (storage_path or "").strip() or None,
                    text,
                    json.dumps(cv_analysis_full or {}),
                    json.dumps(cv_meta or {}),
                    (inferred_title or "").strip() or None,
                    (inferred_seniority or "").strip() or None,
                    json.dumps(top_skills or []),
                    (industry_bucket or "").strip() or None,
                    (inferred_country or "").strip() or None,
                    (source or "carl_individual").strip() or "carl_individual",
                    (consent_note or "").strip() or None,
                    expires_at,
                ),
            )
        return "ok"
    except Exception as exc:
        logger.warning("insert_cv_upload_row failed: %s", exc, exc_info=True)
        return "error"


def link_cv_upload_to_user(session_token: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Attach the latest anon row for ``session_token`` to ``user_id``. Returns merged row fields or ``None``."""
    tok = (session_token or "").strip()
    uid = (user_id or "").strip()
    if not tok or not uid or not SUPABASE_URL:
        return None
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                WITH picked AS (
                    SELECT id FROM cv_uploads
                    WHERE session_token = %s AND user_id IS NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                )
                UPDATE cv_uploads u
                SET user_id = %s::uuid, linked_at = NOW()
                FROM picked p
                WHERE u.id = p.id
                RETURNING u.cv_extracted_text, u.cv_meta, u.cv_analysis_full, u.storage_path
                """,
                (tok, uid),
            )
            row = cur.fetchone()
        if not row:
            return None
        raw_meta, raw_full = row[1], row[2]
        meta: Dict[str, Any]
        if isinstance(raw_meta, dict):
            meta = raw_meta
        else:
            try:
                meta = json.loads(raw_meta) if raw_meta else {}
            except Exception:
                meta = {}
        analysis_full: Optional[Dict[str, Any]]
        if isinstance(raw_full, dict):
            analysis_full = raw_full
        else:
            try:
                analysis_full = json.loads(raw_full) if raw_full else None
            except Exception:
                analysis_full = None
        return {
            "cv_text": row[0] or "",
            "cv_meta": meta,
            "cv_analysis_full": analysis_full,
            "storage_path": row[3],
        }
    except Exception as exc:
        logger.warning("link_cv_upload_to_user failed: %s", exc, exc_info=True)
        return None


def fetch_candidate_demand_signal(industry_bucket: str, country_q: str) -> Optional[Dict[str, Any]]:
    """Return ``{count, window_days}`` from ``candidate_demand_signals`` or ``None`` if zero / unavailable."""
    ib = (industry_bucket or "").strip()
    if not ib or not SUPABASE_URL:
        return None
    cq = (country_q or "").strip()
    try:
        db = get_db()
        with db.cursor() as cur:
            if cq:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(signal_count), 0)::bigint
                    FROM candidate_demand_signals
                    WHERE industry_bucket = %s
                      AND inferred_country = %s
                    """,
                    (ib, cq),
                )
            else:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(signal_count), 0)::bigint
                    FROM candidate_demand_signals
                    WHERE industry_bucket = %s
                    """,
                    (ib,),
                )
            r = cur.fetchone()
            n = int(r[0] or 0) if r else 0
            if n <= 0:
                return None
            return {"count": n, "window_days": 90}
    except Exception as exc:
        logger.info("fetch_candidate_demand_signal skipped: %s", exc)
        return None


def upsert_profile_carl4b2b_analysis(user_id: str, analysis: Optional[Dict[str, Any]] = None) -> str:
    """Update ``profiles.last_carl4b2b_analysis`` for signed-in users (row must exist). Returns ``ok`` or ``error``."""
    uid = (user_id or "").strip()
    if not uid or not SUPABASE_URL:
        return "error"
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE profiles
                SET last_carl4b2b_analysis = %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s::uuid
                """,
                (json.dumps(analysis or {}), uid),
            )
            if cur.rowcount == 0:
                return "error"
        return "ok"
    except Exception as exc:
        logger.warning("upsert_profile_carl4b2b_analysis failed: %s", exc, exc_info=True)
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
            cur.execute(
                "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS cv_url TEXT"
            )
            cur.execute(
                "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS cv_analysis_full JSONB"
            )
            cur.execute(
                "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS last_carl4b2b_analysis JSONB"
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
            # -- perf indexes: salary_submissions LIKE query targets
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_salary_sub_title_loc "
                "ON salary_submissions (job_title, location)"
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cv_uploads (
                    id                 SERIAL PRIMARY KEY,
                    session_token      TEXT        NOT NULL,
                    user_id            UUID,
                    storage_path       TEXT,
                    cv_extracted_text  TEXT        NOT NULL,
                    cv_analysis_full   JSONB,
                    cv_meta             JSONB       NOT NULL DEFAULT '{}'::jsonb,
                    inferred_title      TEXT,
                    inferred_seniority  TEXT,
                    top_skills          JSONB,
                    industry_bucket     TEXT,
                    inferred_country    TEXT,
                    source              TEXT        NOT NULL DEFAULT 'carl_individual',
                    consent_note        TEXT,
                    linked_at           TIMESTAMPTZ,
                    expires_at          TIMESTAMPTZ,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_cv_uploads_session ON cv_uploads(session_token)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_cv_uploads_user ON cv_uploads(user_id) "
                "WHERE user_id IS NOT NULL"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_cv_uploads_created ON cv_uploads(created_at DESC)"
            )
            cur.execute("""
                CREATE OR REPLACE VIEW candidate_demand_signals AS
                SELECT
                    industry_bucket,
                    inferred_country,
                    COUNT(*)::bigint AS signal_count
                FROM cv_uploads
                WHERE created_at > NOW() - INTERVAL '90 days'
                  AND industry_bucket IS NOT NULL
                GROUP BY industry_bucket, inferred_country
            """)
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
    from .catalog import clean_job_description_text
    t = clean_job_description_text(text or "")
    return summarize_two_sentences(t)


