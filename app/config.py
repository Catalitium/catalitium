"""Central configuration constants for Catalitium.

All magic numbers and tunable thresholds live here.
Import from this module rather than scattering literals across the codebase.

Environment-backed secrets and database URL (normalized for psycopg) also
live here so there is a single read surface for the app.
"""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Job search
# ---------------------------------------------------------------------------
PER_PAGE_MAX: int = 100      # Hard cap on results per request (also enforced in DB layer)
GHOST_JOB_DAYS: int = 30     # Jobs older than this are flagged as potentially filled

# ---------------------------------------------------------------------------
# Guest access
# ---------------------------------------------------------------------------
GUEST_DAILY_LIMIT: int = 5_000  # Max job views per day for unauthenticated users

# ---------------------------------------------------------------------------
# In-memory TTL cache settings (used in create_app)
# ---------------------------------------------------------------------------
SUMMARY_CACHE_TTL: int = 90         # seconds
SUMMARY_CACHE_MAX: int = 400

AUTOCOMPLETE_CACHE_TTL: int = 120
AUTOCOMPLETE_CACHE_MAX: int = 400

SALARY_INSIGHTS_CACHE_TTL: int = 120
SALARY_INSIGHTS_CACHE_MAX: int = 250

SITEMAP_CACHE_TTL: int = 3600       # sitemap.xml in-process cache + Cache-Control (seconds)

# ---------------------------------------------------------------------------
# Carl CV demo (Talk to Carl)
# ---------------------------------------------------------------------------
CARL_CHAT_MAX_TURNS: int = 3
CARL_CHAT_MAX_MESSAGE_CHARS: int = 280
CARL_CHAT_MAX_REPLY_CHARS: int = 360

# ---------------------------------------------------------------------------
# Database pool
# ---------------------------------------------------------------------------
DB_POOL_MIN: int = 1
DB_POOL_MAX_DEFAULT: int = 4        # overridden by DB_POOL_MAX env var


def _normalize_pg_url(url: str) -> str:
    """Normalize Postgres URLs for psycopg3 (strip pgbouncer, enforce ssl/timeout)."""
    if not url or not url.startswith(("postgres://", "postgresql://")):
        return url
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    port = parsed.port
    query_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)]
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


_SUPABASE_RAW = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or "").strip()
SUPABASE_URL = _normalize_pg_url(_SUPABASE_RAW)
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", str(DB_POOL_MAX_DEFAULT)))
