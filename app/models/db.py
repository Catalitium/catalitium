# app/models/db.py - Database connection and utility functions

import os
import re
import logging
import sqlite3
import hashlib
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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
    load_dotenv()
except ImportError:
    pass

# ------------------------- Config --------------------------------------------

def _normalize_pg_url(url: str) -> str:
    if not url or not url.startswith(("postgres://", "postgresql://")):
        return url
    parsed = urlparse(url)
    query_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() != "pgbouncer"]
    has_ssl = any(k.lower() == "sslmode" for k, _ in query_pairs)
    if not has_ssl:
        query_pairs.append(("sslmode", "require"))
    new_query = urlencode(query_pairs)
    return urlunparse(parsed._replace(query=new_query))

def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SQLITE_PATH = str(PROJECT_ROOT / "data" / "catalitium.db")

def _sqlite_path() -> str:
    return os.getenv("DB_PATH") or _DEFAULT_SQLITE_PATH

def _should_use_sqlite() -> bool:
    force = os.getenv("FORCE_SQLITE")
    if force is not None:
        return _truthy(force)
    return not bool(os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL"))

# Prefer DATABASE_URL for Postgres; fallback to SUPABASE_URL for backwards-compat
_SUPABASE_RAW = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or "").strip()
SUPABASE_URL = _normalize_pg_url(_SUPABASE_RAW)
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
PER_PAGE_MAX = 100  # safety cap
ANALYTICS_SALT = os.getenv("ANALYTICS_SALT", "dev")
ANALYTICS_SESSION_COOKIE = os.getenv("ANALYTICS_SESSION_COOKIE", "sid")

# ------------------------- Logging -------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("catalitium")

# ------------------------- Database Connection Functions ----------------------

def _pg_connect():
    """Connect to PostgreSQL database."""
    import psycopg
    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL not set")
    conn = psycopg.connect(SUPABASE_URL, autocommit=True)
    # Apply safe session settings (best-effort)
    try:
        with conn.cursor() as cur:
            # Keep queries snappy and fail fast; units in ms
            cur.execute("SET statement_timeout TO 800")
            cur.execute("SET idle_in_transaction_session_timeout TO 5000")
            cur.execute("SET application_name TO 'catalitium'")
    except Exception:
        pass
    return conn

class _SQLiteCursor(sqlite3.Cursor):
    """SQLite cursor supporting context manager and %s-style placeholders."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self.connection.rollback()
            else:
                self.connection.commit()
        finally:
            try:
                self.close()
            except Exception:
                pass
        # Propagate exceptions
        return False

    def _transform_sql(self, sql: str) -> str:
        return sql.replace("%s", "?")

    def execute(self, sql, parameters=None):
        sql = self._transform_sql(sql)
        if parameters is None:
            return super().execute(sql)
        return super().execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters):
        sql = self._transform_sql(sql)
        return super().executemany(sql, seq_of_parameters)

class _SQLiteConnection(sqlite3.Connection):
    """SQLite connection that produces compatible cursors."""

    def cursor(self, factory=None):
        factory = factory or _SQLiteCursor
        return super().cursor(factory)

def _sqlite_connect():
    """Connect to SQLite database (testing / dev fallback)."""
    path = Path(_sqlite_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        path,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        check_same_thread=False,
        factory=_SQLiteConnection,
    )
    conn.row_factory = sqlite3.Row
    return conn

def is_sqlite_connection(conn) -> bool:
    """Return True when the connection object comes from sqlite3."""
    return isinstance(conn, sqlite3.Connection)

def get_db():
    """Get database connection from Flask g object."""
    from flask import g, current_app

    if "db" not in g:
        if _should_use_sqlite():
            try:
                g.db = _sqlite_connect()
            except Exception as e:
                logger.error("SQLite connection failed: %s", e)
                raise
        else:
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
        db.close()

# ------------------------- Subscriber & Analytics Helpers --------------------

def _is_unique_violation(exc: Exception) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    if UniqueViolation is not None and isinstance(exc, UniqueViolation):
        return True
    return False

def _hash(value: str) -> str:
    salted = (ANALYTICS_SALT or "dev").encode("utf-8")
    return hashlib.sha256(salted + (value or "").encode("utf-8")).hexdigest()

def _ensure_session_id() -> str:
    try:
        from flask import g, request
    except RuntimeError:
        return ""
    cookie_name = ANALYTICS_SESSION_COOKIE or "sid"
    sid = request.cookies.get(cookie_name)
    if sid:
        return sid
    sid = uuid.uuid4().hex
    setattr(g, "_analytics_sid_new", (cookie_name, sid))
    return sid

def _client_meta() -> Tuple[str, str, str, str]:
    try:
        from flask import request
    except RuntimeError:
        return ("", "", "", "")
    ua = (request.headers.get("User-Agent") or "")[:300]
    ref = (request.headers.get("Referer") or "")[:300]
    xff = request.headers.get("X-Forwarded-For", "") or ""
    ip = xff.split(",")[0].strip() if xff else (request.remote_addr or "")
    sid = request.cookies.get(ANALYTICS_SESSION_COOKIE or "sid") or _ensure_session_id() or ""
    return (ua, ref, _hash(ip), sid)

def insert_subscriber(email: str) -> str:
    """Insert a subscriber record; return 'ok', 'duplicate', or 'error'."""
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO subscribers(email, created_at) VALUES(%s, %s)",
                (email, _now_iso()),
            )
        return "ok"
    except Exception as exc:
        if _is_unique_violation(exc):
            return "duplicate"
        logger.warning("insert_subscriber failed: %s", exc, exc_info=True)
        return "error"

def insert_subscribe_event(email: str, status: str, *, source: str = "form", job_link: Optional[str] = None) -> None:
    """Persist newsletter events within the unified analytics table."""
    meta = {"source": (source or "form")[:50]}
    if job_link:
        meta["job_link"] = job_link
    insert_search_event(
        raw_title="subscribe",
        raw_country="",
        norm_title="subscribe",
        norm_country="",
        sal_floor=None,
        sal_ceiling=None,
        result_count=0,
        page=0,
        per_page=0,
        source=source,
        event_type="subscribe",
        event_status=status,
        job_id=None,
        job_title=None,
        job_company=None,
        job_location=None,
        job_link=job_link,
        job_summary=None,
        email_hash=_hash(email or ""),
        meta=meta,
    )

def insert_search_event(
    *,
    raw_title: str,
    raw_country: str,
    norm_title: str,
    norm_country: str,
    sal_floor: Optional[int],
    sal_ceiling: Optional[int],
    result_count: int,
    page: int,
    per_page: int,
    source: str = "server",
    event_type: str = "search",
    event_status: Optional[str] = None,
    job_id: Optional[str] = None,
    job_title: Optional[str] = None,
    job_company: Optional[str] = None,
    job_location: Optional[str] = None,
    job_link: Optional[str] = None,
    job_summary: Optional[str] = None,
    email_hash: Optional[str] = None,
    meta: Optional[Dict[str, str]] = None,
) -> None:
    """Persist analytics events (search, apply, subscribe, filter) in a single table."""
    db = get_db()
    ua, ref, ip_hash, sid = _client_meta()
    safe_event_type = (event_type or "search").strip() or "search"
    safe_event_status = (event_status or ("ok" if safe_event_type == "search" else "")).strip()

    safe_job_title = (job_title or "").strip()
    safe_job_company = (job_company or "").strip()
    safe_job_location = (job_location or "").strip()
    safe_job_link = (job_link or "").strip()
    safe_job_summary = (job_summary or "").strip()

    safe_raw_title = (raw_title or safe_job_title).strip() or "N/A"
    safe_raw_country = (raw_country or safe_job_location).strip() or "N/A"
    safe_norm_title = (norm_title or ("apply" if safe_event_type == "apply" else "")).strip()
    safe_norm_country = (norm_country or "").strip()

    safe_email_hash = (email_hash or "").strip()
    meta_json = ""
    if meta:
        meta_clean: Dict[str, str] = {}
        for key, value in meta.items():
            if key is None or value is None:
                continue
            meta_clean[str(key)[:50]] = str(value)[:200]
        if meta_clean:
            meta_json = json.dumps(meta_clean, separators=(",", ":"), ensure_ascii=False)[:1000]

    payload = (
        _now_iso(),
        safe_raw_title,
        safe_raw_country,
        safe_norm_title,
        safe_norm_country,
        int(sal_floor) if sal_floor is not None else None,
        int(sal_ceiling) if sal_ceiling is not None else None,
        int(result_count),
        int(page),
        int(per_page),
        ua,
        ref,
        ip_hash,
        sid,
        (source or "server")[:50],
        safe_event_status[:50] if safe_event_status else "",
        safe_event_type[:20],
        (job_id or "").strip()[:160],
        safe_job_title[:300],
        safe_job_company[:200],
        safe_job_location[:200],
        safe_job_link[:500],
        safe_job_summary[:400],
        safe_email_hash[:200],
        meta_json,
    )
    try:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO log_events(
                    created_at,
                    raw_title,
                    raw_country,
                    norm_title,
                    norm_country,
                    sal_floor,
                    sal_ceiling,
                    result_count,
                    page,
                    per_page,
                    user_agent,
                    referer,
                    ip_hash,
                    session_id,
                    source,
                    event_status,
                    event_type,
                    job_id,
                    job_title_event,
                    job_company_event,
                    job_location_event,
                    job_link_event,
                    job_summary_event,
                    email_hash,
                    meta_json
                ) VALUES(
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                """,
                payload,
            )
    except Exception as exc:
        logger.debug("log analytics skipped: %s", exc)

# ------------------------- Description Parsing ------------------------------

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
    "de","la","el","en","y","los","las","que","es","un","una","con","por","para","le","et","Ã ",
    "les","des","est","pour","dans"
}

def summarize_two_sentences(text: str) -> str:
    """Extract two most representative sentences from text (pure stdlib)."""
    import re
    from collections import Counter
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
    t = clean_job_description_text(text or "")
    return summarize_two_sentences(t)

def _ensure_sqlite_columns(db, table: str, definitions: Dict[str, str]) -> None:
    try:
        rows = db.execute(f"PRAGMA table_info('{table}')").fetchall()
    except Exception as exc:
        logger.debug("Unable to inspect %s columns: %s", table, exc)
        return
    existing = {row[1] for row in rows}
    for column, ddl in definitions.items():
        if column not in existing:
            try:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
            except Exception as exc:
                logger.debug("Unable to add %s to %s: %s", column, table, exc)

def _ensure_postgres_columns(db, table: str, definitions: Dict[str, str]) -> None:
    try:
        with db.cursor() as cur:
            for column, ddl in definitions.items():
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {ddl}")
    except Exception as exc:
        logger.debug("Unable to ensure columns for %s: %s", table, exc)


def init_db():
    """Ensure required tables exist in the primary Postgres database (or SQLite)."""
    db = get_db()

    if is_sqlite_connection(db):
        db.executescript(
            """
            -- ---------------------- SQLite ----------------------

            CREATE TABLE IF NOT EXISTS salary (
                geo_salary_id    INTEGER PRIMARY KEY,
                location         TEXT,
                median_salary    REAL,
                min_salary       REAL,
                currency_ticker  TEXT,
                city             TEXT,
                country          TEXT,
                region           TEXT,
                remote_type      TEXT,
                loaded_at        TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_salary_country     ON salary(country);
            CREATE INDEX IF NOT EXISTS idx_salary_city        ON salary(city);
            CREATE INDEX IF NOT EXISTS idx_salary_region      ON salary(region);
            CREATE INDEX IF NOT EXISTS idx_salary_remote_type ON salary(remote_type);

            
            CREATE TABLE IF NOT EXISTS subscribers (
                email TEXT PRIMARY KEY,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS log_events (
                id INTEGER PRIMARY KEY,
                created_at TEXT,
                raw_title TEXT,
                raw_country TEXT,
                norm_title TEXT,
                norm_country TEXT,
                sal_floor INTEGER,
                sal_ceiling INTEGER,
                result_count INTEGER,
                page INTEGER,
                per_page INTEGER,
                user_agent TEXT,
                referer TEXT,
                ip_hash TEXT,
                session_id TEXT,
                source TEXT DEFAULT 'server',
                event_status TEXT,
                event_type TEXT DEFAULT 'search',
                job_id TEXT,
                job_title_event TEXT,
                job_company_event TEXT,
                job_location_event TEXT,
                job_link_event TEXT,
                job_summary_event TEXT,
                email_hash TEXT,
                meta_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_log_events_created ON log_events(created_at);

            /* Unified jobs table (consolidated date TEXT, consolidated link, robot_code default 0) */
            CREATE TABLE IF NOT EXISTS jobs (
                id               INTEGER PRIMARY KEY,
                job_id           TEXT,
                job_title        TEXT,
                job_title_norm   TEXT,
                normalized_job   TEXT,
                company_name     TEXT,
                job_description  TEXT,
                location         TEXT,
                city             TEXT,
                region           TEXT,
                country          TEXT,
                geo_id           TEXT,
                robot_code       INTEGER NOT NULL DEFAULT 0,
                link             TEXT,
                salary           TEXT,
                date             TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_link_unique   ON jobs(link);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_job_id_unique ON jobs(job_id);
            CREATE INDEX  IF NOT EXISTS idx_jobs_title_norm          ON jobs(job_title_norm);
            CREATE INDEX  IF NOT EXISTS idx_jobs_location            ON jobs(location);
            CREATE INDEX  IF NOT EXISTS idx_jobs_date                ON jobs(date);

            /* Companies table (CompanyID -> id) */
            CREATE TABLE IF NOT EXISTS companies (
                id             INTEGER PRIMARY KEY,
                company_name   TEXT NOT NULL,
                website        TEXT,
                industry       TEXT,
                headcount      INTEGER,
                founded_year   INTEGER,
                location       TEXT,
                about          TEXT,
                specialties    TEXT,
                tags           TEXT,
                web_summary    TEXT,
                contact_email  TEXT,
                page_score     INTEGER
            );

            CREATE INDEX  IF NOT EXISTS idx_companies_name               ON companies(company_name);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_website_unique ON companies(website);

            CREATE TABLE IF NOT EXISTS leads (
                id            INTEGER PRIMARY KEY,
                link          TEXT NOT NULL,
                robot_status  INTEGER NOT NULL DEFAULT 0,
                date          TEXT CHECK (date IS NULL OR date GLOB '????-??-??T??:??:??Z')
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_link_unique ON leads(link);
            CREATE INDEX  IF NOT EXISTS idx_leads_date         ON leads(date);
            """
        )

        _ensure_sqlite_columns(
            db,
            "log_events",
            {
                "sal_floor": "sal_floor INTEGER",
                "sal_ceiling": "sal_ceiling INTEGER",
                "user_agent": "user_agent TEXT",
                "referer": "referer TEXT",
                "ip_hash": "ip_hash TEXT",
                "session_id": "session_id TEXT",
                "source": "source TEXT DEFAULT 'server'",
                "event_status": "event_status TEXT",
                "event_type": "event_type TEXT DEFAULT 'search'",
                "job_id": "job_id TEXT",
                "job_title_event": "job_title_event TEXT",
                "job_company_event": "job_company_event TEXT",
                "job_location_event": "job_location_event TEXT",
                "job_link_event": "job_link_event TEXT",
                "job_summary_event": "job_summary_event TEXT",
                "email_hash": "email_hash TEXT",
                "meta_json": "meta_json TEXT",
            },
        )
        _ensure_sqlite_columns(
            db,
            "jobs",
            {
                "job_id": "job_id TEXT",
                "job_title_norm": "job_title_norm TEXT",
                "normalized_job": "normalized_job TEXT",
                "company_name": "company_name TEXT",
                "city": "city TEXT",
                "region": "region TEXT",
                "country": "country TEXT",
                "geo_id": "geo_id TEXT",
                "robot_code": "robot_code INTEGER DEFAULT 0",
                "salary": "salary TEXT",
                "date": "date TEXT",
            },
        )
        _ensure_sqlite_columns(
            db,
            "companies",
            {
                "company_name": "company_name TEXT",
                "website": "website TEXT",
                "industry": "industry TEXT",
                "headcount": "headcount INTEGER",
                "founded_year": "founded_year INTEGER",
                "location": "location TEXT",
                "about": "about TEXT",
                "specialties": "specialties TEXT",
                "tags": "tags TEXT",
                "web_summary": "web_summary TEXT",
                "contact_email": "contact_email TEXT",
                "page_score": "page_score INTEGER",
            },
        )
        db.commit()
        return

    # --------------------------- Postgres ---------------------------
    with db.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS subscribers (
                email TEXT UNIQUE,
                created_at TIMESTAMP
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS log_events (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP,
                raw_title TEXT NULL,
                raw_country TEXT NULL,
                norm_title TEXT NULL,
                norm_country TEXT NULL,
                sal_floor INTEGER NULL,
                sal_ceiling INTEGER NULL,
                result_count INTEGER,
                page INTEGER,
                per_page INTEGER,
                user_agent TEXT NULL,
                referer TEXT NULL,
                ip_hash TEXT NULL,
                session_id TEXT NULL,
                source TEXT DEFAULT 'server',
                event_status TEXT,
                event_type TEXT DEFAULT 'search',
                job_id TEXT,
                job_title_event TEXT,
                job_company_event TEXT,
                job_location_event TEXT,
                job_link_event TEXT,
                job_summary_event TEXT,
                email_hash TEXT,
                meta_json TEXT
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id               SERIAL PRIMARY KEY,
                job_id           TEXT,
                job_title        TEXT,
                job_title_norm   TEXT,
                normalized_job   TEXT,
                company_name     TEXT,
                job_description  TEXT,
                location         TEXT,
                city             TEXT,
                region           TEXT,
                country          TEXT,
                geo_id           TEXT,
                robot_code       INTEGER NOT NULL DEFAULT 0,
                link             TEXT,
                salary           TEXT,
                date             TEXT
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS companies (
                id             SERIAL PRIMARY KEY,
                company_name   TEXT NOT NULL,
                website        TEXT,
                industry       TEXT,
                headcount      INTEGER,
                founded_year   INTEGER,
                location       TEXT,
                about          TEXT,
                specialties    TEXT,
                tags           TEXT,
                web_summary    TEXT,
                contact_email  TEXT,
                page_score     INTEGER
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id SERIAL PRIMARY KEY,
                link TEXT NOT NULL,
                robot_status INTEGER NOT NULL DEFAULT 0,
                date TEXT
            );
            """
        )

    _ensure_postgres_columns(
        db,
        "log_events",
        {
            "sal_floor": "sal_floor INTEGER",
            "sal_ceiling": "sal_ceiling INTEGER",
            "user_agent": "user_agent TEXT",
            "referer": "referer TEXT",
            "ip_hash": "ip_hash TEXT",
            "session_id": "session_id TEXT",
            "source": "source TEXT DEFAULT 'server'",
            "event_status": "event_status TEXT",
            "event_type": "event_type TEXT DEFAULT 'search'",
            "job_id": "job_id TEXT",
            "job_title_event": "job_title_event TEXT",
            "job_company_event": "job_company_event TEXT",
            "job_location_event": "job_location_event TEXT",
            "job_link_event": "job_link_event TEXT",
            "job_summary_event": "job_summary_event TEXT",
            "email_hash": "email_hash TEXT",
            "meta_json": "meta_json TEXT",
        },
    )
    _ensure_postgres_columns(
        db,
        "jobs",
        {
            "job_id": "job_id TEXT",
            "job_title_norm": "job_title_norm TEXT",
            "normalized_job": "normalized_job TEXT",
            "company_name": "company_name TEXT",
            "job_description": "job_description TEXT",
            "location": "location TEXT",
            "city": "city TEXT",
            "region": "region TEXT",
            "country": "country TEXT",
            "geo_id": "geo_id TEXT",
            "robot_code": "robot_code INTEGER DEFAULT 0",
            "link": "link TEXT",
            "salary": "salary TEXT",
            "date": "date TEXT",
        },
    )
    _ensure_postgres_columns(
        db,
        "companies",
        {
            "company_name": "company_name TEXT",
            "website": "website TEXT",
            "industry": "industry TEXT",
            "headcount": "headcount INTEGER",
            "founded_year": "founded_year INTEGER",
            "location": "location TEXT",
            "about": "about TEXT",
            "specialties": "specialties TEXT",
            "tags": "tags TEXT",
            "web_summary": "web_summary TEXT",
            "contact_email": "contact_email TEXT",
            "page_score": "page_score INTEGER",
        },
    )
    _ensure_postgres_columns(
        db,
        "leads",
        {
            "link": "link TEXT",
            "robot_status": "robot_status INTEGER DEFAULT 0",
            "date": "date TEXT",
        },
    )

    with db.cursor() as cur:
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_log_events_created ON log_events(created_at);""")
        cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_link_unique   ON jobs(link) WHERE link IS NOT NULL;""")
        cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_job_id_unique ON jobs(job_id) WHERE job_id IS NOT NULL;""")
        cur.execute("""CREATE INDEX  IF NOT EXISTS idx_jobs_title_norm          ON jobs(job_title_norm);""")
        cur.execute("""CREATE INDEX  IF NOT EXISTS idx_jobs_location            ON jobs(location);""")
        cur.execute("""CREATE INDEX  IF NOT EXISTS idx_jobs_date                ON jobs(date);""")
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(company_name);""")
        cur.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_website_unique ON companies(website) WHERE website IS NOT NULL;"""
        )
        cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_link_unique ON leads(link);""")
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_leads_date ON leads(date);""")

# ------------------------- Analytics Helpers ---------------------------------

def _now_iso():
    """Get current timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

# ------------------------- Helper Functions ----------------------------------

# ------------------------- Normalization Functions ---------------------------

COUNTRY_NORM = {
    "deutschland":"DE","germany":"DE","deu":"DE","de":"DE",
    "switzerland":"CH","schweiz":"CH","suisse":"CH","svizzera":"CH","ch":"CH",
    "austria":"AT","Ã¶sterreich":"AT","at":"AT",
    "europe":"EU","eu":"EU","eur":"EU","european union":"EU",
    "uk":"UK","gb":"UK","england":"UK","united kingdom":"UK",
    "usa":"US","united states":"US","america":"US","us":"US",
    "spain":"ES","es":"ES","france":"FR","fr":"FR","italy":"IT","it":"IT",
    "netherlands":"NL","nl":"NL","belgium":"BE","be":"BE","sweden":"SE","se":"SE",
    "poland":"PL","colombia":"CO","mexico":"MX",
    "portugal":"PT","ireland":"IE","denmark":"DK","finland":"FI","greece":"GR",
    "hungary":"HU","romania":"RO","slovakia":"SK","slovenia":"SI","bulgaria":"BG",
    "croatia":"HR","cyprus":"CY","czech republic":"CZ","czechia":"CZ","estonia":"EE",
    "latvia":"LV","lithuania":"LT","luxembourg":"LU","malta":"MT",
}

LOCATION_COUNTRY_HINTS = {
    "amsterdam": "NL",
    "atlanta": "US",
    "austin": "US",
    "barcelona": "ES",
    "belgium": "BE",
    "berlin": "DE",
    "berlin, de": "DE",
    "boston": "US",
    "brussels": "BE",
    "budapest": "HU",
    "charlotte": "US",
    "chicago": "US",
    "copenhagen": "DK",
    "dallas": "US",
    "denmark": "DK",
    "denver": "US",
    "dublin": "IE",
    "france": "FR",
    "frankfurt": "DE",
    "germany": "DE",
    "hamburg": "DE",
    "houston": "US",
    "italy": "IT",
    "lisbon": "PT",
    "london": "UK",
    "los angeles": "US",
    "los": "US",
    "madrid": "ES",
    "miami": "US",
    "milan": "IT",
    "minneapolis": "US",
    "munich": "DE",
    "netherlands": "NL",
    "new york": "US",
    "oslo": "NO",
    "paris": "FR",
    "philadelphia": "US",
    "phoenix": "US",
    "pittsburgh": "US",
    "portland": "US",
    "porto": "PT",
    "portugal": "PT",
    "prague": "CZ",
    "raleigh": "US",
    "salt lake city": "US",
    "salt": "US",
    "san francisco": "US",
    "seattle": "US",
    "spain": "ES",
    "stockholm": "SE",
    "switzerland": "CH",
    "tallinn": "EE",
    "uk": "UK",
    "vienna": "AT",
    "washington": "US",
    "zurich": "CH",
}

TITLE_SYNONYMS = {
    "swe":"software engineer","software eng":"software engineer","sw eng":"software engineer",
    "frontend":"front end","front-end":"front end","backend":"back end","back-end":"back end",
    "fullstack":"full stack","full-stack":"full stack",
    "pm":"product manager","prod mgr":"product manager","product owner":"product manager",
    "ds":"data scientist","ml":"machine learning","mle":"machine learning engineer",
    "sre":"site reliability engineer","devops":"devops","sec eng":"security engineer","infosec":"security",
    "programmer":"developer","coder":"developer",
}

def normalize_country(q: str) -> str:
    """Return normalized country code if possible."""
    if not q:
        return ""
    t = q.strip().lower()
    if t in COUNTRY_NORM:
        return COUNTRY_NORM[t]
    if len(t) == 2 and t.isalpha():
        return t.upper()
    for token, code in COUNTRY_NORM.items():
        if re.search(rf"\b{re.escape(token)}\b", t):
            return code
    return q.strip()

def normalize_title(q: str) -> str:
    """Normalize job title query."""
    if not q:
        return ""
    s = q.lower()
    for k, v in TITLE_SYNONYMS.items():
        if k in s:
            s = s.replace(k, v)
    s = re.sub(r"[^\w\s\-\/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ------------------------- Job Model ----------------------------------------

class Job:
    table = "jobs"
    _EU_CODES: Set[str] = {
        "AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE",
        "IT","LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE"
    }
    _EU_FILTER_CODES: Set[str] = {"DE", "ES", "NL"}

    @staticmethod
    def _normalize_title(value: Optional[str]) -> str:
        return (value or "").strip().lower()

    @staticmethod
    def _escape_like(value: str) -> str:
        value = value.replace("\\", "\\\\")
        value = value.replace("%", r"\%")
        value = value.replace("_", r"\_")
        return value

    @staticmethod
    def _country_patterns(codes: Iterable[str]) -> Tuple[List[str], List[str]]:
        seps_before = [" ", "(", ",", "/", "-"]
        seps_after = [" ", ")", ",", "/", "-"]
        patterns: List[str] = []
        equals: Set[str] = set()
        seen_like: Set[str] = set()

        def add_like(pattern: str) -> None:
            if pattern not in seen_like:
                patterns.append(pattern)
                seen_like.add(pattern)

        normalized_codes = {code.upper() for code in codes if code}
        for code in normalized_codes:
            token = Job._escape_like(code.lower())
            equals.add(code.lower())
            for before in seps_before:
                for after in seps_after:
                    add_like(f"%{before}{token}{after}%")
                add_like(f"%{before}{token}")
            if len(code) > 2:
                add_like(f"%{token}%")

        if "EU" in normalized_codes:
            add_like(f"%{Job._escape_like('eu')}%")

        aliases: Set[str] = set()
        for alias, mapped in COUNTRY_NORM.items():
            if mapped.upper() in normalized_codes and len(alias) > 2:
                aliases.add(alias.lower())
        for alias in sorted(aliases):
            add_like(f"%{Job._escape_like(alias)}%")

        for hint, mapped in LOCATION_COUNTRY_HINTS.items():
            if mapped.upper() in normalized_codes:
                add_like(f"%{Job._escape_like(hint)}%")
                if len(hint) <= 3:
                    equals.add(hint)

        return patterns, sorted(equals)

    @staticmethod
    def count(title: Optional[str] = None, country: Optional[str] = None) -> int:
        """Return number of jobs matching optional filters."""
        where_sql, params_sqlite, params_pg = Job._where(title, country)
        db = get_db()
        with db.cursor() as cur:
            if is_sqlite_connection(db):
                cur.execute(f"SELECT COUNT(1) FROM jobs {where_sql['sqlite']}", params_sqlite)
            else:
                cur.execute(f"SELECT COUNT(1) FROM jobs {where_sql['pg']}", params_pg)
            row = cur.fetchone()
            return int(row[0] if row else 0)

    @staticmethod
    def search(
        title: Optional[str] = None,
        country: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict]:
        """Return matching jobs ordered by recency."""
        where_sql, params_sqlite, params_pg = Job._where(title, country)
        db = get_db()
        use_sqlite = is_sqlite_connection(db)
        where_clause = where_sql["sqlite"] if use_sqlite else where_sql["pg"]
        params = list(params_sqlite if use_sqlite else params_pg)
        sql = f"""
            SELECT
                id,
                job_id,
                job_title,
                job_title_norm,
                normalized_job,
                company_name,
                job_description,
                location,
                city,
                region,
                country,
                geo_id,
                robot_code,
                link,
                salary,
                date
            FROM jobs {where_clause}
            {Job._order_by(country)}
            LIMIT %s OFFSET %s
        """
        params.extend([int(limit), int(offset)])
        with db.cursor() as cur:
            cur.execute(sql, params)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    @staticmethod
    def insert_many(rows: List[Dict]) -> int:
        """Bulk insert jobs, ignoring duplicates by link."""
        if not rows:
            return 0
        cols = [
            "job_id",
            "job_title",
            "job_title_norm",
            "normalized_job",
            "company_name",
            "job_description",
            "location",
            "city",
            "region",
            "country",
            "geo_id",
            "robot_code",
            "link",
            "salary",
            "date",
        ]
        placeholders = ", ".join(["%s"] * len(cols))
        sql = f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT (link) DO NOTHING"

        payload = []
        for row in rows:
            title = row.get("job_title") or row.get("title") or ""
            job_id = (
                row.get("job_id")
                or row.get("jobId")
                or row.get("id")
                or row.get("external_id")
                or row.get("externalId")
            )
            job_title_norm = Job._normalize_title(row.get("job_title_norm") or title)
            normalized_job = row.get("normalized_job") or job_title_norm
            company_name = (
                row.get("company_name")
                or row.get("company")
                or row.get("employer")
                or row.get("job_company")
                or ""
            )
            location = row.get("location") or row.get("job_location") or ""
            city = row.get("city") or ""
            region = row.get("region") or ""
            country = row.get("country") or row.get("country_code") or ""
            geo_id = row.get("geo_id") or row.get("geo") or ""
            robot_code = row.get("robot_code") or row.get("robotCode") or row.get("robot") or 0
            try:
                robot_code_int = int(robot_code)
            except Exception:
                robot_code_int = 0
            link = row.get("link") or row.get("job_link") or row.get("url") or ""
            salary = row.get("salary") or row.get("compensation") or ""
            date_value = (
                row.get("date")
                or row.get("job_date")
                or row.get("date_posted")
                or row.get("posted_at")
                or ""
            )
            payload.append(
                (
                    job_id,
                    title,
                    job_title_norm,
                    normalized_job,
                    company_name,
                    row.get("job_description") or row.get("description") or "",
                    location,
                    city,
                    region,
                    country,
                    geo_id,
                    robot_code_int,
                    link,
                    salary,
                    date_value,
                )
            )

        db = None
        close_after = False
        try:
            try:
                db = get_db()
            except RuntimeError:
                db = _sqlite_connect() if _should_use_sqlite() else _pg_connect()
                close_after = True
            with db.cursor() as cur:
                cur.executemany(sql, payload)
                return cur.rowcount or 0
        finally:
            if close_after and db:
                try:
                    db.close()
                except Exception:
                    pass

    @staticmethod
    def get_link(job_id: Optional[str]) -> Optional[str]:
        """Return the outbound link for a job id if available."""
        if job_id is None:
            return None
        value = str(job_id).strip()
        if not value:
            return None
        try:
            value_param = int(value)
        except (TypeError, ValueError):
            return None

        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT link FROM jobs WHERE id = %s", [value_param])
            row = cur.fetchone()
        if not row:
            return None

        link = None
        try:
            if isinstance(row, dict):
                link = row.get("link")
            elif hasattr(row, "keys"):
                link = row["link"]
            elif hasattr(row, "link"):
                link = row.link
            elif hasattr(row, "__getitem__"):
                link = row[0]
        except Exception:
            link = None
        return link.strip() if isinstance(link, str) else None

    @staticmethod
    def _where(title: Optional[str], country: Optional[str]) -> Tuple[Dict[str, str], Tuple[str, ...], Tuple[str, ...]]:
        clauses_pg: List[str] = []
        clauses_sqlite: List[str] = []
        params_pg: List[str] = []
        params_sqlite: List[str] = []

        if title:
            t_norm = Job._normalize_title(title)
            if t_norm:
                tokens = [tok for tok in t_norm.split() if tok]
                specials = {"remote", "developer"}
                remote_flag = "remote" in tokens
                developer_flag = "developer" in tokens
                core_tokens = [tok for tok in tokens if tok not in specials]
                core_query = " ".join(core_tokens).strip()

                if core_query:
                    like = f"%{Job._escape_like(core_query)}%"
                    clause_pg = "(job_title_norm ILIKE %s ESCAPE '\\' OR LOWER(job_title) LIKE %s ESCAPE '\\' OR LOWER(job_description) LIKE %s ESCAPE '\\')"
                    clause_sqlite = "(job_title_norm LIKE ? ESCAPE '\\' OR LOWER(job_title) LIKE ? ESCAPE '\\' OR LOWER(job_description) LIKE ? ESCAPE '\\')"
                    clauses_pg.append(clause_pg)
                    clauses_sqlite.append(clause_sqlite)
                    params_pg.extend([like, like, like])
                    params_sqlite.extend([like, like, like])

                if remote_flag:
                    remote_like = f"%{Job._escape_like('remote')}%"
                    clause_pg_remote = "(job_title_norm ILIKE %s ESCAPE '\\' OR LOWER(job_title) LIKE %s ESCAPE '\\' OR LOWER(job_description) LIKE %s ESCAPE '\\' OR LOWER(location) LIKE %s ESCAPE '\\')"
                    clause_sqlite_remote = "(job_title_norm LIKE ? ESCAPE '\\' OR LOWER(job_title) LIKE ? ESCAPE '\\' OR LOWER(job_description) LIKE ? ESCAPE '\\' OR LOWER(location) LIKE ? ESCAPE '\\')"
                    clauses_pg.append(clause_pg_remote)
                    clauses_sqlite.append(clause_sqlite_remote)
                    params_pg.extend([remote_like, remote_like, remote_like, remote_like])
                    params_sqlite.extend([remote_like, remote_like, remote_like, remote_like])

                if developer_flag:
                    dev_terms = ["developer", "programmer", "coder", "software developer", "software engineer"]
                    patterns = [f"%{Job._escape_like(term)}%" for term in dev_terms]
                    clause_pg_terms: List[str] = []
                    clause_sqlite_terms: List[str] = []
                    for _ in dev_terms:
                        clause_pg_terms.extend([
                            "job_title_norm ILIKE %s ESCAPE '\\'",
                            "LOWER(job_title) LIKE %s ESCAPE '\\'",
                            "LOWER(job_description) LIKE %s ESCAPE '\\'",
                        ])
                        clause_sqlite_terms.extend([
                            "job_title_norm LIKE ? ESCAPE '\\'",
                            "LOWER(job_title) LIKE ? ESCAPE '\\'",
                            "LOWER(job_description) LIKE ? ESCAPE '\\'",
                        ])
                    clause_pg_dev = "(" + " OR ".join(clause_pg_terms) + ")"
                    clause_sqlite_dev = "(" + " OR ".join(clause_sqlite_terms) + ")"
                    clauses_pg.append(clause_pg_dev)
                    clauses_sqlite.append(clause_sqlite_dev)
                    for pattern in patterns:
                        params_pg.extend([pattern, pattern, pattern])
                        params_sqlite.extend([pattern, pattern, pattern])

        if country:
            c_raw = (country or "").strip().lower()
            if c_raw:
                patterns_like: List[str] = []
                equals_exact: List[str] = []
                upper = c_raw.upper()
                code = upper if len(upper) == 2 and upper.isalpha() else None

                if upper == "HIGH_PAY":
                    high_pay_cities = ["new york", "san francisco", "zurich"]
                    for city in high_pay_cities:
                        patterns_like.append(f"%{Job._escape_like(city)}%")
                        equals_exact.append(city)
                elif upper == "EU":
                    patterns_like, equals_exact = Job._country_patterns(Job._EU_FILTER_CODES | {"EU"})
                elif upper == "CH":
                    patterns_like, equals_exact = Job._country_patterns({"CH"})
                elif code:
                    patterns_like, equals_exact = Job._country_patterns({code})
                else:
                    patterns_like = [f"%{Job._escape_like(c_raw)}%"]

                columns_to_search = ("location", "city", "region", "country")
                subclauses_pg: List[str] = []
                subclauses_sqlite: List[str] = []

                if patterns_like:
                    like_terms_pg: List[str] = []
                    like_terms_sqlite: List[str] = []
                    for pattern in patterns_like:
                        for column in columns_to_search:
                            like_terms_pg.append(
                                f"LOWER(COALESCE({column}, '')) LIKE %s ESCAPE '\\'"
                            )
                            like_terms_sqlite.append(
                                f"LOWER(COALESCE({column}, '')) LIKE ? ESCAPE '\\'"
                            )
                            params_pg.append(pattern)
                            params_sqlite.append(pattern)
                    if like_terms_pg:
                        subclauses_pg.append("(" + " OR ".join(like_terms_pg) + ")")
                        subclauses_sqlite.append("(" + " OR ".join(like_terms_sqlite) + ")")

                if equals_exact:
                    equals_terms_pg: List[str] = []
                    equals_terms_sqlite: List[str] = []
                    for value in equals_exact:
                        value_lower = value.lower()
                        for column in columns_to_search:
                            equals_terms_pg.append(
                                f"LOWER(COALESCE({column}, '')) = %s"
                            )
                            equals_terms_sqlite.append(
                                f"LOWER(COALESCE({column}, '')) = ?"
                            )
                            params_pg.append(value_lower)
                            params_sqlite.append(value_lower)
                    if equals_terms_pg:
                        subclauses_pg.append("(" + " OR ".join(equals_terms_pg) + ")")
                        subclauses_sqlite.append("(" + " OR ".join(equals_terms_sqlite) + ")")

                if subclauses_pg:
                    clause_pg = "(" + " OR ".join(subclauses_pg) + ")"
                    clause_sqlite = "(" + " OR ".join(subclauses_sqlite) + ")"
                    clauses_pg.append(clause_pg)
                    clauses_sqlite.append(clause_sqlite)

        where_pg = f"WHERE {' AND '.join(clauses_pg)}" if clauses_pg else ""
        where_sqlite = f"WHERE {' AND '.join(clauses_sqlite)}" if clauses_sqlite else ""
        return {"pg": where_pg, "sqlite": where_sqlite}, tuple(params_sqlite), tuple(params_pg)

    @staticmethod
    def _order_by(country: Optional[str]) -> str:
        if not country:
            return "ORDER BY (date IS NULL) ASC, date DESC, id DESC"
        code = country.strip().upper()
        if code == "EU":
            return "ORDER BY RANDOM()"
        if code == "HIGH_PAY":
            return (
                "ORDER BY CASE "
                "WHEN LOWER(location) LIKE '%san francisco%' THEN 0 "
                "WHEN LOWER(location) LIKE '%new york%' THEN 1 "
                "WHEN LOWER(location) LIKE '%zurich%' THEN 2 "
                "ELSE 3 END, "
                "(date IS NULL) ASC, date DESC, id DESC"
            )
        return "ORDER BY (date IS NULL) ASC, date DESC, id DESC"

# ------------------------- Salary Parsing Functions --------------------------

def parse_money_numbers(text: str):
    """Parse money numbers from text."""
    if not text:
        return []
    nums = []
    for raw in re.findall(r'(?i)\d[\d,.\s]*k?', text):
        clean = raw.lower().replace(",", "").replace(" ", "")
        mult = 1000 if clean.endswith("k") else 1
        clean = clean.rstrip("k").replace(".", "")
        if clean.isdigit():
            nums.append(int(clean) * mult)
    return nums

def parse_salary_query(q: str):
    """Parse inline salary filters like '80k-120k', '>100k', '<=90k', '120k'."""
    if not q:
        return ("", None, None)
    s = q.strip()

    range_match = re.search(r'(?i)(\d[\d,.\s]*k?)\s*[-\u2013]\s*(\d[\d,.\s]*k?)', s)
    if range_match:
        low_vals = parse_money_numbers(range_match.group(1))
        high_vals = parse_money_numbers(range_match.group(2))
        cleaned = (s[:range_match.start()] + s[range_match.end():]).strip()
        return cleaned, low_vals[0] if low_vals else None, high_vals[-1] if high_vals else None

    greater_match = re.search(r'(?i)>\s*=?\s*(\d[\d,.\s]*k?)', s)
    if greater_match:
        vals = parse_money_numbers(greater_match.group(1))
        cleaned = (s[:greater_match.start()] + s[greater_match.end():]).strip()
        return cleaned, vals[0] if vals else None, None

    less_match = re.search(r'(?i)<\s*=?\s*(\d[\d,.\s]*k?)', s)
    if less_match:
        vals = parse_money_numbers(less_match.group(1))
        cleaned = (s[:less_match.start()] + s[less_match.end():]).strip()
        return cleaned, None, vals[0] if vals else None

    single_match = re.search(r'(?i)(\d[\d,.\s]*k?)', s)
    if single_match:
        vals = parse_money_numbers(single_match.group(1))
        cleaned = (s[:single_match.start()] + s[single_match.end():]).strip()
        return cleaned, vals[0] if vals else None, None

    # No inline salary filter found — return cleaned query and no bounds
    return s, None, None


def get_salary_for_location(location: str):
    """Best-effort: return median_salary (float) for a location string.

    Matching strategy (in order):
    - exact city match
    - exact region match
    - exact country match
    - fallback: location contained in salary.location / salary.city / salary.region
    Returns None when no reasonable match found.
    """
    if not location:
        return None
    loc = str(location).strip()
    if not loc:
        return None
    db = get_db()
    # normalize pieces
    pieces = [p.strip() for p in re.split(r"[,;/\\-]|\\(|\\)", loc) if p and p.strip()]
    # try city, region, country in that order
    candidates = []
    if pieces:
        candidates.extend(pieces)
    # also try the full string
    candidates.append(loc)

    try:
        with db.cursor() as cur:
            # try exact matches first
            for cand in candidates:
                if not cand:
                    continue
                cur.execute(
                    "SELECT median_salary, currency_ticker FROM salary WHERE lower(city) = lower(%s) AND median_salary IS NOT NULL LIMIT 1",
                    (cand,),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    return float(row[0]), (row[1] or None)
            for cand in candidates:
                if not cand:
                    continue
                cur.execute(
                    "SELECT median_salary, currency_ticker FROM salary WHERE lower(region) = lower(%s) AND median_salary IS NOT NULL LIMIT 1",
                    (cand,),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    return float(row[0]), (row[1] or None)
            for cand in candidates:
                if not cand:
                    continue
                cur.execute(
                    "SELECT median_salary, currency_ticker FROM salary WHERE lower(country) = lower(%s) AND median_salary IS NOT NULL LIMIT 1",
                    (cand,),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    return float(row[0]), (row[1] or None)

            # fallback: LIKE search in combined fields
            like_term = f"%{loc.lower()}%"
            cur.execute(
                "SELECT median_salary, currency_ticker FROM salary WHERE (lower(location) LIKE %s OR lower(city) LIKE %s OR lower(region) LIKE %s) AND median_salary IS NOT NULL LIMIT 1",
                (like_term, like_term, like_term),
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                return float(row[0]), (row[1] or None)
    except Exception:
        # Best-effort: ignore DB errors and return None
        return None
    return None


def _compact_salary_number(n: float) -> str:
    """Return a compact string like '110k' or '1.2M' for a numeric salary.

    Uses thousands (k) and millions (M). Rounds to a sensible 10k grid for
    thousands (so ranges look tidy).
    """
    if n is None:
        return ""
    try:
        v = float(n)
    except Exception:
        return str(n)
    if v < 1000:
        return str(int(round(v)))
    # work in thousands
    k = int(round(v / 1000.0))
    if k < 1000:
        # round to nearest 10 (10k granularity)
        k_rounded = int(round(k / 10.0) * 10)
        if k_rounded <= 0:
            k_rounded = max(1, k)
        return f"{k_rounded}k"
    # millions
    m = v / 1_000_000.0
    # one decimal for millions
    m_rounded = round(m, 1)
    # drop .0 when integer
    if m_rounded.is_integer():
        return f"{int(m_rounded)}M"
    return f"{m_rounded}M"


def salary_range_around(median: float, pct: float = 0.2):
    """Return (low, high) numeric range around median using pct (default 20%).

    Also provide compact display strings (rounded to 10k grid for thousands).
    """
    if median is None:
        return None
    try:
        m = float(median)
    except Exception:
        return None
    low = m * (1.0 - pct)
    high = m * (1.0 + pct)
    # round: floor low to nearest 10k, ceil high to nearest 10k when in thousands
    def _round_floor_10k(x):
        if x < 1000:
            return int(x)
        k = int(x // 1000)
        k_floor = (k // 10) * 10
        if k_floor <= 0:
            k_floor = max(1, k)
        return k_floor * 1000

    def _round_ceil_10k(x):
        if x < 1000:
            return int(x)
        k = int((x + 999) // 1000)
        k_ceil = ((k + 9) // 10) * 10
        if k_ceil <= 0:
            k_ceil = max(1, k)
        return k_ceil * 1000

    low_r = _round_floor_10k(low)
    high_r = _round_ceil_10k(high)
    return (low_r, high_r, _compact_salary_number(low_r), _compact_salary_number(high_r))

    return (s, None, None)


# ------------------------- Formatting Helpers ------------------------------

def format_job_date_string(s: str) -> str:
    """Normalize job date strings for display.
    - If 'YYYYMMDD' -> 'YYYY.MM.DD'
    - If 'YYYY-MM-DD' -> 'YYYY.MM.DD'
    - Otherwise return original trimmed string
    """
    if not s:
        return ""
    s = str(s).strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo}-{d}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo}-{d}"
    iso_candidate = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_candidate)
        return dt.date().isoformat()
    except ValueError:
        pass
    prefix_match = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if prefix_match:
        return prefix_match.group(1)
    return s

def clean_job_description_text(text: str) -> str:
    """Clean description by removing leading relative-age prefixes and stray labels."""
    if not text:
        return ""
    t = str(text)
    # Strip any leading non-word characters followed by an 8 digit date (e.g., 20251009)
    t = re.sub(r"^\s*\W*\d{8}\s*\n?", "", t)
    # Strip leading relative age prefixes like "11 hours ago - "
    t = re.sub(r"^\s*\d+\s*(minutes?|hours?|days?|weeks?)\s+ago\s+[^\w\s]\s*", "", t, flags=re.IGNORECASE)
    # Remove a standalone leading 'Details' line
    t = re.sub(r"^\s*Details\s*\n+", "", t, flags=re.IGNORECASE)
    return t.strip()
