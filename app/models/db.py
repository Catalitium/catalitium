# app/models/db.py - Database connection and utility functions

import os
import re
import logging
import hashlib
import uuid
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse, quote

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
    hostname = parsed.hostname or ""
    port = parsed.port
    # Supabase pooled hosts use pgbouncer on 6543; the UI sometimes shows 5432.
    if hostname.endswith(".pooler.supabase.com") and (port is None or port == 5432):
        port = 6543
    # Keep existing params and add safe defaults.
    query_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)]
    # Drop params psycopg/libpq will reject (Supabase adds pgbouncer=true for pooled URLs).
    query_pairs = [(k, v) for k, v in query_pairs if k.lower() != "pgbouncer"]
    has_ssl = any(k.lower() == "sslmode" for k, _ in query_pairs)
    if not has_ssl:
        query_pairs.append(("sslmode", "require"))
    has_connect_timeout = any(k.lower() == "connect_timeout" for k, _ in query_pairs)
    if not has_connect_timeout:
        query_pairs.append(("connect_timeout", "5"))
    new_query = urlencode(query_pairs)
    auth = ""
    user = quote(parsed.username) if parsed.username else ""
    pwd = quote(parsed.password) if parsed.password else ""
    if user:
        auth = user
        if parsed.password:
            auth += f":{pwd}"
        auth += "@"
    hostport = hostname
    if port:
        hostport = f"{hostname}:{port}"
    parsed = parsed._replace(netloc=f"{auth}{hostport}")
    return urlunparse(parsed._replace(query=new_query))

def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SQLITE_PATH = str(PROJECT_ROOT / "data" / "catalitium.db")

def _sqlite_path() -> str:
    return os.getenv("DB_PATH") or _DEFAULT_SQLITE_PATH

# Prefer DATABASE_URL for Postgres; fallback to SUPABASE_URL for backwards-compat
_SUPABASE_RAW = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or "").strip()
SUPABASE_URL = _normalize_pg_url(_SUPABASE_RAW)
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
PER_PAGE_MAX = 100  # safety cap
ANALYTICS_SALT = os.getenv("ANALYTICS_SALT", "dev")
ANALYTICS_SESSION_COOKIE = os.getenv("ANALYTICS_SESSION_COOKIE", "sid")
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "4"))

# ------------------------- Logging -------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("catalitium")

# ------------------------- Database Connection Functions ----------------------
_PG_POOL = None

def _setup_connection(conn):
    """Apply session settings and ensure autocommit."""
    try:
        conn.autocommit = True
    except Exception:
        pass
    try:
        with conn.cursor() as cur:
            # Keep queries snappy and fail fast; units in ms
            cur.execute("SET statement_timeout TO 800")
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
            conn = _PG_POOL.connection()
            _setup_connection(conn)
            return conn
        except Exception as exc:
            logger.warning("Pool connection failed, retrying direct connect: %s", exc)
            _PG_POOL = None
    # Fallback: direct connection
    import psycopg
    conn = psycopg.connect(SUPABASE_URL, autocommit=True)
    _setup_connection(conn)
    return conn


def _pg_connect():
    """Connect to PostgreSQL database."""
    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL not set")
    return _acquire_connection()

def get_db():
    """Get database connection from Flask g object."""
    from flask import g, current_app

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
        db.close()

# ------------------------- Subscriber & Analytics Helpers --------------------

def _is_unique_violation(exc: Exception) -> bool:
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
    """Lightweight connectivity check; Supabase owns schema/migrations."""
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as exc:
        logger.warning("init_db connectivity check failed: %s", exc)

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
    "india":"IN","bharat":"IN","in":"IN",
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
    # India hubs
    "bangalore": "IN",
    "bengaluru": "IN",
    "mumbai": "IN",
    "pune": "IN",
    "delhi": "IN",
    "new delhi": "IN",
    "gurgaon": "IN",
    "gurugram": "IN",
    "noida": "IN",
    "hyderabad": "IN",
    "chennai": "IN",
    "kolkata": "IN",
    "ahmedabad": "IN",
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
    # Use full EU set for filter matching so EU queries return broad results.
    _EU_FILTER_CODES: Set[str] = set(_EU_CODES)
    _CACHE_TTL = 30  # seconds
    _CACHE_MAX = 128
    _cache_count: Dict[Tuple[str, str], Tuple[float, int]] = {}
    _cache_search: Dict[Tuple[str, str, int, int], Tuple[float, List[Dict]]] = {}

    @staticmethod
    def _cache_prune(target: Dict):
        if len(target) <= Job._CACHE_MAX:
            return
        # Drop oldest entries to keep memory bounded
        oldest = sorted(target.items(), key=lambda kv: kv[1][0])[: len(target) - Job._CACHE_MAX]
        for key, _ in oldest:
            target.pop(key, None)

    @staticmethod
    def _cache_get_count(key: Tuple[str, str]) -> Optional[int]:
        now = time.time()
        hit = Job._cache_count.get(key)
        if hit and now - hit[0] < Job._CACHE_TTL:
            return hit[1]
        return None

    @staticmethod
    def _cache_set_count(key: Tuple[str, str], value: int) -> None:
        Job._cache_count[key] = (time.time(), int(value))
        Job._cache_prune(Job._cache_count)

    @staticmethod
    def _cache_get_search(key: Tuple[str, str, int, int]) -> Optional[List[Dict]]:
        now = time.time()
        hit = Job._cache_search.get(key)
        if hit and now - hit[0] < Job._CACHE_TTL:
            return hit[1]
        return None

    @staticmethod
    def _cache_set_search(key: Tuple[str, str, int, int], value: List[Dict]) -> None:
        Job._cache_search[key] = (time.time(), value)
        Job._cache_prune(Job._cache_search)

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
            if code == "IN":
                equals.update({"in", "india"})
                india_aliases = {
                    "india","bharat","bangalore","bengaluru","mumbai","pune","delhi","new delhi",
                    "gurgaon","gurugram","noida","hyderabad","chennai","kolkata","ahmedabad"
                }
                for alias in india_aliases:
                    add_like(f"%{Job._escape_like(alias)}%")
                continue

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
        key = ((title or "").strip().lower(), (country or "").strip().lower())
        cached = Job._cache_get_count(key)
        if cached is not None:
            return cached
        where_sql, _params_sqlite, params_pg = Job._where(title, country)
        db = get_db()
        with db.cursor() as cur:
            cur.execute(f"SELECT COUNT(1) FROM jobs {where_sql['pg']}", params_pg)
            row = cur.fetchone()
            value = int(row[0] if row else 0)
            Job._cache_set_count(key, value)
            return value

    @staticmethod
    def search(
        title: Optional[str] = None,
        country: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict]:
        """Return matching jobs ordered by recency."""
        key = (
            (title or "").strip().lower(),
            (country or "").strip().lower(),
            int(limit),
            int(offset),
        )
        cached = Job._cache_get_search(key)
        if cached is not None:
            return cached
        where_sql, _params_sqlite, params_pg = Job._where(title, country)
        db = get_db()
        where_clause = where_sql["pg"]
        params = list(params_pg)
        sql = f"""
            SELECT
                id,
                job_title,
                job_title_norm,
                company_name,
                job_description,
                location,
                country,
                link,
                date
            FROM jobs {where_clause}
            {Job._order_by(country)}
            LIMIT %s OFFSET %s
        """
        params.extend([int(limit), int(offset)])
        with db.cursor() as cur:
            cur.execute(sql, params)
            cols = [desc[0] for desc in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            Job._cache_set_search(key, rows)
            return rows

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
                db = _pg_connect()
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
                upper = c_raw.upper()
                code = upper if len(upper) == 2 and upper.isalpha() else None

                # City hubs for EU and India to tighten matching.
                eu_hubs = ["madrid", "paris", "berlin", "barcelona", "milan", "milano"]
                india_hubs = [
                    "bangalore",
                    "bengaluru",
                    "mumbai",
                    "pune",
                    "delhi",
                    "new delhi",
                    "gurgaon",
                    "gurugram",
                    "noida",
                    "hyderabad",
                    "chennai",
                    "kolkata",
                    "ahmedabad",
                ]

                subclauses_pg: List[str] = []
                subclauses_sqlite: List[str] = []
                columns_to_search = ("location", "city", "region", "country")

                if upper == "HIGH_PAY":
                    high_pay_cities = [
                        "san francisco",
                        "new york",
                        "zurich",
                        "berlin",
                        "paris",
                        "madrid",
                        "london",
                    ]
                    placeholders_pg = ", ".join(["%s"] * len(high_pay_cities))
                    placeholders_sqlite = ", ".join(["?"] * len(high_pay_cities))
                    city_clause_pg = f"LOWER(COALESCE(city, '')) IN ({placeholders_pg})"
                    city_clause_sqlite = f"LOWER(COALESCE(city, '')) IN ({placeholders_sqlite})"
                    params_pg.extend([c.lower() for c in high_pay_cities])
                    params_sqlite.extend([c.lower() for c in high_pay_cities])
                    subclauses_pg.append(city_clause_pg)
                    subclauses_sqlite.append(city_clause_sqlite)
                elif upper == "EU":
                    # Exact country codes + key hubs; avoid wide LIKE scans.
                    eu_codes = sorted(Job._EU_FILTER_CODES)
                    placeholders_pg = ", ".join(["%s"] * len(eu_codes))
                    placeholders_sqlite = ", ".join(["?"] * len(eu_codes))
                    country_clause_pg = f"LOWER(COALESCE(country, '')) IN ({placeholders_pg})"
                    country_clause_sqlite = f"LOWER(COALESCE(country, '')) IN ({placeholders_sqlite})"
                    params_pg.extend([c.lower() for c in eu_codes])
                    params_sqlite.extend([c.lower() for c in eu_codes])
                    subclauses_pg.append(country_clause_pg)
                    subclauses_sqlite.append(country_clause_sqlite)

                    if eu_hubs:
                        hub_placeholders_pg = ", ".join(["%s"] * len(eu_hubs))
                        hub_placeholders_sqlite = ", ".join(["?"] * len(eu_hubs))
                        city_clause_pg = f"LOWER(COALESCE(city, '')) IN ({hub_placeholders_pg})"
                        city_clause_sqlite = f"LOWER(COALESCE(city, '')) IN ({hub_placeholders_sqlite})"
                        params_pg.extend([h.lower() for h in eu_hubs])
                        params_sqlite.extend([h.lower() for h in eu_hubs])
                        subclauses_pg.append(city_clause_pg)
                        subclauses_sqlite.append(city_clause_sqlite)
                elif code == "IN":
                    # Strict match on country plus key Indian cities.
                    subclauses_pg.append("LOWER(COALESCE(country, '')) = %s")
                    subclauses_sqlite.append("LOWER(COALESCE(country, '')) = ?")
                    params_pg.append("in")
                    params_sqlite.append("in")

                    hub_placeholders_pg = ", ".join(["%s"] * len(india_hubs))
                    hub_placeholders_sqlite = ", ".join(["?"] * len(india_hubs))
                    city_clause_pg = f"LOWER(COALESCE(city, '')) IN ({hub_placeholders_pg})"
                    city_clause_sqlite = f"LOWER(COALESCE(city, '')) IN ({hub_placeholders_sqlite})"
                    params_pg.extend([h.lower() for h in india_hubs])
                    params_sqlite.extend([h.lower() for h in india_hubs])
                    subclauses_pg.append(city_clause_pg)
                    subclauses_sqlite.append(city_clause_sqlite)
                elif upper == "CH":
                    patterns_like, equals_exact = Job._country_patterns({"CH"})
                    if equals_exact:
                        eq_pg = []
                        eq_sqlite = []
                        for value in equals_exact:
                            value_lower = value.lower()
                            for column in columns_to_search:
                                eq_pg.append(f"LOWER(COALESCE({column}, '')) = %s")
                                eq_sqlite.append(f"LOWER(COALESCE({column}, '')) = ?")
                                params_pg.append(value_lower)
                                params_sqlite.append(value_lower)
                        if eq_pg:
                            subclauses_pg.append("(" + " OR ".join(eq_pg) + ")")
                            subclauses_sqlite.append("(" + " OR ".join(eq_sqlite) + ")")
                    if patterns_like:
                        like_pg = []
                        like_sqlite = []
                        for pattern in patterns_like:
                            for column in columns_to_search:
                                like_pg.append(f"LOWER(COALESCE({column}, '')) LIKE %s ESCAPE '\\'")
                                like_sqlite.append(f"LOWER(COALESCE({column}, '')) LIKE ? ESCAPE '\\'")
                                params_pg.append(pattern)
                                params_sqlite.append(pattern)
                        if like_pg:
                            subclauses_pg.append("(" + " OR ".join(like_pg) + ")")
                            subclauses_sqlite.append("(" + " OR ".join(like_sqlite) + ")")
                elif code:
                    patterns_like, equals_exact = Job._country_patterns({code})
                    if equals_exact:
                        eq_pg = []
                        eq_sqlite = []
                        for value in equals_exact:
                            value_lower = value.lower()
                            for column in columns_to_search:
                                eq_pg.append(f"LOWER(COALESCE({column}, '')) = %s")
                                eq_sqlite.append(f"LOWER(COALESCE({column}, '')) = ?")
                                params_pg.append(value_lower)
                                params_sqlite.append(value_lower)
                        if eq_pg:
                            subclauses_pg.append("(" + " OR ".join(eq_pg) + ")")
                            subclauses_sqlite.append("(" + " OR ".join(eq_sqlite) + ")")
                    if patterns_like:
                        like_pg = []
                        like_sqlite = []
                        for pattern in patterns_like:
                            for column in columns_to_search:
                                like_pg.append(f"LOWER(COALESCE({column}, '')) LIKE %s ESCAPE '\\'")
                                like_sqlite.append(f"LOWER(COALESCE({column}, '')) LIKE ? ESCAPE '\\'")
                                params_pg.append(pattern)
                                params_sqlite.append(pattern)
                        if like_pg:
                            subclauses_pg.append("(" + " OR ".join(like_pg) + ")")
                            subclauses_sqlite.append("(" + " OR ".join(like_sqlite) + ")")
                else:
                    pattern = f"%{Job._escape_like(c_raw)}%"
                    like_pg = []
                    like_sqlite = []
                    for column in columns_to_search:
                        like_pg.append(f"LOWER(COALESCE({column}, '')) LIKE %s ESCAPE '\\'")
                        like_sqlite.append(f"LOWER(COALESCE({column}, '')) LIKE ? ESCAPE '\\'")
                        params_pg.append(pattern)
                        params_sqlite.append(pattern)
                    if like_pg:
                        subclauses_pg.append("(" + " OR ".join(like_pg) + ")")
                        subclauses_sqlite.append("(" + " OR ".join(like_sqlite) + ")")

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
            # Favor key EU hubs without forcing a full-table shuffle.
            return (
                "ORDER BY CASE "
                "WHEN LOWER(location) LIKE '%%madrid%%' THEN 0 "
                "WHEN LOWER(location) LIKE '%%paris%%' THEN 1 "
                "WHEN LOWER(location) LIKE '%%berlin%%' THEN 2 "
                "WHEN LOWER(location) LIKE '%%barcelona%%' THEN 3 "
                "WHEN LOWER(location) LIKE '%%milan%%' THEN 4 "
                "WHEN LOWER(location) LIKE '%%milano%%' THEN 5 "
                "ELSE 6 END, "
                "(date IS NULL) ASC, date DESC, id DESC"
            )
        if code == "HIGH_PAY":
            return (
                "ORDER BY CASE "
                "WHEN LOWER(location) LIKE '%%san francisco%%' THEN 0 "
                "WHEN LOWER(location) LIKE '%%new york%%' THEN 1 "
                "WHEN LOWER(location) LIKE '%%zurich%%' THEN 2 "
                "WHEN LOWER(location) LIKE '%%berlin%%' THEN 3 "
                "WHEN LOWER(location) LIKE '%%paris%%' THEN 4 "
                "WHEN LOWER(location) LIKE '%%madrid%%' THEN 5 "
                "WHEN LOWER(location) LIKE '%%london%%' THEN 6 "
                "ELSE 7 END, "
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
    # Supabase Postgres schema: median_salary, min_salary, currency
    median_col = "median_salary"
    currency_col = "currency"
    # normalize pieces
    pieces = [p.strip() for p in re.split(r"[,;/\\-]|\\(|\\)", loc) if p and p.strip()]
    # try city, region, country in that order
    candidates: List[str] = []
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
                    f"SELECT {median_col}, {currency_col} FROM salary WHERE lower(city) = lower(%s) AND {median_col} IS NOT NULL LIMIT 1",
                    (cand,),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    return float(row[0]), (row[1] or None)
            for cand in candidates:
                if not cand:
                    continue
                cur.execute(
                    f"SELECT {median_col}, {currency_col} FROM salary WHERE lower(region) = lower(%s) AND {median_col} IS NOT NULL LIMIT 1",
                    (cand,),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    return float(row[0]), (row[1] or None)
            for cand in candidates:
                if not cand:
                    continue
                cur.execute(
                    f"SELECT {median_col}, {currency_col} FROM salary WHERE lower(country) = lower(%s) AND {median_col} IS NOT NULL LIMIT 1",
                    (cand,),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    return float(row[0]), (row[1] or None)

            # fallback: LIKE search in combined fields
            like_term = f"%{loc.lower()}%"
            cur.execute(
                f"""
                SELECT {median_col}, {currency_col}
                FROM salary
                WHERE (
                    lower(location) LIKE %s
                    OR lower(city) LIKE %s
                    OR lower(region) LIKE %s
                )
                AND {median_col} IS NOT NULL
                LIMIT 1
                """,
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
