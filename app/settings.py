"""Environment-backed settings for DB and secrets (single read surface for the app)."""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse, quote

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

from .config import DB_POOL_MAX_DEFAULT


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
