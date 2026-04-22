"""Carl4B2B Brave Search integration.

External context only. Never contributes to Ghost Score, Salary Drift, or any
existing analysis metric. Fails silently (returns ``None``) when the API key is
missing, Brave is unreachable, the request times out, or the response is
malformed. Uses the stdlib ``urllib`` so no new Python dependencies are added.

Public surface:
    - BRAVE_SESSION_LIMIT        — hard cap per Flask session
    - BRAVE_CACHE                — module-level 24h TTLCache (shared across users)
    - BraveContextType           — Literal["company", "role_market", "competitor"]
    - build_query(ctx_type, meta) -> str
    - fetch_brave_context(query, *, api_key, now=None) -> list[dict] | None
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..utils import TTLCache

logger = logging.getLogger("catalitium")

BraveContextType = Literal["company", "role_market", "competitor"]

BRAVE_API_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
BRAVE_TIMEOUT_SECONDS = 3
BRAVE_SESSION_LIMIT = 3
BRAVE_RESULT_MAX = 5
BRAVE_SNIPPET_MAX_CHARS = 200
BRAVE_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h
BRAVE_CACHE_MAX_ENTRIES = 500

BRAVE_CACHE = TTLCache(ttl_seconds=BRAVE_CACHE_TTL_SECONDS, max_size=BRAVE_CACHE_MAX_ENTRIES)

_VALID_CONTEXT_TYPES = ("company", "role_market", "competitor")
_WHITESPACE_RE = re.compile(r"\s+")


def _truncate(value: str, limit: int) -> str:
    if not value:
        return ""
    s = str(value)
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _normalize_query_token(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "").strip())


def build_query(context_type: str, meta: Dict[str, Any]) -> str:
    """Deterministic query string for a given context type and analysis meta.

    ``meta`` is expected to contain any of: company (str), title (str),
    country (str), top_hirers (list[str]). Missing values are skipped so
    the final query stays short and relevant.
    """
    ctx = (context_type or "").strip().lower()
    if ctx not in _VALID_CONTEXT_TYPES:
        return ""

    year = datetime.now(timezone.utc).year
    company = _normalize_query_token(str(meta.get("company") or ""))
    title = _normalize_query_token(str(meta.get("title") or ""))
    country = _normalize_query_token(str(meta.get("country") or ""))
    top_hirers = meta.get("top_hirers") or []
    if not isinstance(top_hirers, (list, tuple)):
        top_hirers = []
    top_hirers = [
        _normalize_query_token(str(x))
        for x in top_hirers
        if _normalize_query_token(str(x))
    ][:3]

    if ctx == "company":
        if not company:
            return ""
        return f'"{company}" hiring news {year}'

    if ctx == "role_market":
        parts: List[str] = []
        if title:
            parts.append(f'"{title}"')
        parts.append("hiring market")
        if country:
            parts.append(country)
        parts.append(str(year))
        return " ".join(parts).strip()

    if ctx == "competitor":
        if not top_hirers:
            return ""
        quoted = " OR ".join(f'"{h}"' for h in top_hirers)
        return f"{quoted} hiring announcements {year}"

    return ""


def _parse_brave_payload(payload: Any) -> List[Dict[str, str]]:
    """Best-effort normalization of a Brave Search JSON response.

    Returns up to ``BRAVE_RESULT_MAX`` items with string fields truncated.
    Any parsing error for an individual item is silently skipped — we never
    raise from parse.
    """
    if not isinstance(payload, dict):
        return []
    web = payload.get("web") if isinstance(payload.get("web"), dict) else {}
    items = web.get("results") if isinstance(web, dict) else None
    if not isinstance(items, list):
        return []

    out: List[Dict[str, str]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            title = _truncate(str(raw.get("title") or ""), BRAVE_SNIPPET_MAX_CHARS)
            url = str(raw.get("url") or "").strip()
            description = _truncate(
                str(raw.get("description") or ""),
                BRAVE_SNIPPET_MAX_CHARS,
            )
            age = _truncate(str(raw.get("age") or ""), 64)
        except Exception:  # defensive; never raise from parser
            continue
        if not title or not url:
            continue
        if not (url.startswith("https://") or url.startswith("http://")):
            continue
        out.append(
            {
                "title": title,
                "url": url,
                "description": description,
                "age": age,
            }
        )
        if len(out) >= BRAVE_RESULT_MAX:
            break
    return out


def _cache_key(query: str) -> str:
    return "brave:v1:" + _normalize_query_token(query).lower()


def fetch_brave_context(
    query: str,
    *,
    api_key: Optional[str] = None,
    now: Optional[datetime] = None,  # accepted for test injection; unused internally
) -> Optional[List[Dict[str, str]]]:
    """Fetch (or return cached) Brave Search results for ``query``.

    Returns a list of normalized snippet dicts on success, ``None`` on any
    failure (missing key, network error, timeout, non-200 response,
    unparseable body). Callers must treat ``None`` as "external context
    unavailable" and never block the main analysis path on it.
    """
    del now  # reserved for future deterministic-clock tests

    q = _normalize_query_token(query)
    if not q:
        return None

    cache_key = _cache_key(q)
    cached = BRAVE_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)

    key = (api_key or os.getenv("BRAVE_SEARCH_API_KEY") or "").strip()
    if not key:
        return None

    params = {
        "q": q,
        "count": str(BRAVE_RESULT_MAX),
        "safesearch": "moderate",
    }
    url = f"{BRAVE_API_ENDPOINT}?{urlencode(params)}"
    req = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "X-Subscription-Token": key,
            "User-Agent": "catalitium-carl4b2b/1.0",
        },
    )

    start = time.time()
    try:
        with urlopen(req, timeout=BRAVE_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                logger.info("brave: non-200 status=%s q=%r", status, q)
                return None
            raw_body = resp.read()
    except HTTPError as exc:
        logger.info("brave: http_error status=%s q=%r", getattr(exc, "code", "?"), q)
        return None
    except URLError as exc:
        logger.info("brave: url_error reason=%r q=%r", getattr(exc, "reason", "?"), q)
        return None
    except Exception as exc:  # defensive; never raise
        logger.warning("brave: unexpected error type=%s q=%r", type(exc).__name__, q)
        return None

    elapsed_ms = int((time.time() - start) * 1000)
    logger.info("brave: ok elapsed_ms=%s bytes=%s", elapsed_ms, len(raw_body or b""))

    try:
        payload = json.loads(raw_body.decode("utf-8", errors="replace"))
    except Exception:
        return None

    normalized = _parse_brave_payload(payload)
    if not normalized:
        # Cache empty result briefly-ish to avoid pounding Brave on a bad query.
        # Same TTL for simplicity; UI treats empty list as "no external signals".
        BRAVE_CACHE.set(cache_key, [])
        return []

    BRAVE_CACHE.set(cache_key, normalized)
    return list(normalized)


__all__ = [
    "BraveContextType",
    "BRAVE_API_ENDPOINT",
    "BRAVE_CACHE",
    "BRAVE_RESULT_MAX",
    "BRAVE_SESSION_LIMIT",
    "BRAVE_SNIPPET_MAX_CHARS",
    "BRAVE_TIMEOUT_SECONDS",
    "build_query",
    "fetch_brave_context",
]
