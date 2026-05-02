"""app/utils.py — Shared utility surface for Catalitium.

Sections (in order):
  TTL caches · API response helpers · Pure utilities · Email validation
  Normalization · Link blacklist · Flask route helpers (CSRF, pagination, API)
  guest_daily_remaining/consume

Subscriber sanitization / honeypot / salary percentiles: ``app.models.subscribers``,
``app.models.money``.
"""

from __future__ import annotations

# ── stdlib ──────────────────────────────────────────────────────────────────
import functools
import hashlib
import json
import logging
import os
import re
import secrets
import smtplib
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

# ── Flask (proxies; safe for blueprint-level imports) ────────────────────────
from flask import after_this_request, current_app, g, jsonify, request, session

# ── App config ───────────────────────────────────────────────────────────────
from .config import (
    AUTOCOMPLETE_CACHE_MAX,
    AUTOCOMPLETE_CACHE_TTL,
    GHOST_JOB_DAYS,
    GUEST_DAILY_LIMIT,
    PER_PAGE_MAX,
    SALARY_INSIGHTS_CACHE_MAX,
    SALARY_INSIGHTS_CACHE_TTL,
    SUMMARY_CACHE_MAX,
    SUMMARY_CACHE_TTL,
)

logger = logging.getLogger("catalitium")

# ============================================================================
# ── Cache ────────────────────────────────────────────────────────────────────
# ============================================================================


class TTLCache:
    """Simple in-memory TTL cache suitable for low-volume API responses."""

    def __init__(self, ttl_seconds: int = 60, max_size: int = 500) -> None:
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_size = max(10, int(max_size))
        self._store: Dict[str, tuple[float, Any]] = {}

    def _prune(self) -> None:
        now = time.time()
        expired = [k for k, (ts, _) in self._store.items() if now - ts > self.ttl_seconds]
        for key in expired:
            self._store.pop(key, None)
        if len(self._store) <= self.max_size:
            return
        oldest = sorted(self._store.items(), key=lambda kv: kv[1][0])[: len(self._store) - self.max_size]
        for key, _ in oldest:
            self._store.pop(key, None)

    def get(self, key: str) -> Any:
        hit = self._store.get(key)
        if not hit:
            return None
        ts, value = hit
        if time.time() - ts > self.ttl_seconds:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._prune()
        self._store[key] = (time.time(), value)


# Named module-level cache singletons (A2) — import these instead of constructing inline.
SUMMARY_CACHE = TTLCache(ttl_seconds=SUMMARY_CACHE_TTL, max_size=SUMMARY_CACHE_MAX)
AUTOCOMPLETE_CACHE = TTLCache(ttl_seconds=AUTOCOMPLETE_CACHE_TTL, max_size=AUTOCOMPLETE_CACHE_MAX)
SALARY_CACHE = TTLCache(ttl_seconds=SALARY_INSIGHTS_CACHE_TTL, max_size=SALARY_INSIGHTS_CACHE_MAX)

# ============================================================================
# ── API response helpers ─────────────────────────────────────────────────────
# ============================================================================


def generate_request_id() -> str:
    """Return a short request correlation id."""
    return uuid.uuid4().hex[:12]


def api_ok(
    *,
    data: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    message: str = "ok",
    code: str = "ok",
) -> Dict[str, Any]:
    """Return a normalized success envelope."""
    return {
        "ok": True,
        "code": code,
        "message": message,
        "request_id": request_id or "",
        "data": data or {},
    }


def api_fail(
    *,
    code: str,
    message: str,
    request_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a normalized error envelope."""
    return {
        "ok": False,
        "code": code,
        "message": message,
        "request_id": request_id or "",
        "details": details or {},
    }


def parse_int_arg(
    args: Mapping[str, Any],
    key: str,
    *,
    default: int,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    """Parse and clamp an integer query parameter."""
    raw = args.get(key, default)
    try:
        value = int(raw)  # type: ignore[arg-type]
    except Exception:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def parse_str_arg(args: Mapping[str, Any], key: str, *, default: str = "", max_len: int = 200) -> str:
    """Parse and trim a string query parameter."""
    value = str(args.get(key, default) or "").strip()
    return value[:max_len]


# ============================================================================
# ── Pure utility functions ───────────────────────────────────────────────────
# ============================================================================


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug (max 60 chars)."""
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:60]


def slugify_job_title(title: str) -> str:
    """Stable slug for job titles (HTTP tests, sitemap-style normalization)."""
    return slugify(title or "")


def to_lc(value: str) -> str:
    """Return a lowercase camel-style version of a string for API responses."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", value or "") if p]
    if not parts:
        return value or ""
    head, *tail = parts
    return head.lower() + "".join(part.capitalize() for part in tail)


def coerce_datetime(value) -> Optional[datetime]:
    """Convert assorted datetime-like inputs into timezone-aware datetimes when possible."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_datetime"):
        try:
            return value.to_datetime()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            iso = value.isoformat()
            return datetime.fromisoformat(iso)
        except Exception:
            pass
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except Exception:
            continue
    return None


def job_is_new(job_date_raw, row_date) -> bool:
    """Return True when the job was posted within the last 7 days."""
    dt = coerce_datetime(row_date) or coerce_datetime(job_date_raw)
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt) <= timedelta(days=7)


def job_is_ghost(job_date_raw) -> bool:
    """Return True when the job was posted more than GHOST_JOB_DAYS ago (may be filled)."""
    dt = coerce_datetime(job_date_raw)
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt) > timedelta(days=GHOST_JOB_DAYS)


def now_iso() -> str:
    """Return current UTC time as ISO-8601 string (canonical, R2)."""
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# ── Email validation (R3: merged format check + disposable domain check) ─────
# ============================================================================

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

_DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "guerrillamailblock.com",
    "sharklasers.com", "yopmail.com", "yopmail.net", "trashmail.com",
    "tempmail.com", "dispostable.com", "maildrop.cc", "getairmail.com",
    "10minutemail.com", "fakeinbox.com", "burnermail.io", "trashmail.de",
    "mailnesia.com", "mailcatch.com", "temp-mail.org", "emailondeck.com",
    "throwaway.email", "grr.la", "moza.pl", "byom.de", "spam4.me",
    "mailnull.com", "mailscrap.com", "tmpmail.net", "tmpmail.org",
})


class EmailNotValidError(ValueError):
    """Raised when an email address fails basic format validation."""


def validate_email(
    address: str,
    *,
    check_disposable: bool = False,
    check_deliverability: bool = False,
):
    """Lightweight email validator. Returns object with .normalized.

    Raises EmailNotValidError on bad format.
    When check_disposable=True, also raises for known throwaway domains.

    ``check_deliverability`` is accepted for backward compatibility; it is
    not used (no DNS/MX deliverability checks).
    """
    _ = check_deliverability  # legacy kw from older factory call sites
    class _Result:
        normalized: str

    r = _Result()
    r.normalized = (address or "").strip().lower()
    if not _EMAIL_RE.match(r.normalized):
        raise EmailNotValidError(f"Invalid email: {address!r}")
    if check_disposable and disposable_email_domain(r.normalized):
        raise EmailNotValidError(f"Disposable email not allowed: {address!r}")
    return r


def disposable_email_domain(email: str) -> bool:
    """True for known throwaway inboxes (best-effort list)."""
    at = (email or "").rfind("@")
    if at < 0:
        return False
    dom = email[at + 1:].lower().strip()
    if dom in _DISPOSABLE_DOMAINS:
        return True
    return any(dom.endswith("." + d) for d in _DISPOSABLE_DOMAINS)


# ============================================================================
# ── Normalization ─────────────────────────────────────────────────────────────
# ============================================================================


def _load_country_norm() -> Dict[str, str]:
    _path = Path(__file__).parent / "data" / "country_norm.json"
    try:
        with open(_path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("country_norm.json load failed: %s", exc)
        return {}


COUNTRY_NORM: Dict[str, str] = _load_country_norm()

LOCATION_COUNTRY_HINTS: Dict[str, str] = {
    "amsterdam": "NL", "atlanta": "US", "austin": "US",
    "barcelona": "ES", "belgium": "BE", "berlin": "DE", "berlin, de": "DE",
    "boston": "US", "brussels": "BE", "budapest": "HU",
    "charlotte": "US", "chicago": "US", "copenhagen": "DK",
    "dallas": "US", "denmark": "DK", "denver": "US", "dublin": "IE",
    "france": "FR", "frankfurt": "DE", "germany": "DE", "hamburg": "DE",
    "houston": "US", "italy": "IT", "lisbon": "PT", "london": "UK",
    "los angeles": "US", "los": "US", "madrid": "ES", "miami": "US",
    "milan": "IT", "minneapolis": "US", "munich": "DE",
    "netherlands": "NL", "new york": "US", "oslo": "NO", "paris": "FR",
    "philadelphia": "US", "phoenix": "US", "pittsburgh": "US",
    "portland": "US", "porto": "PT", "portugal": "PT", "prague": "CZ",
    "raleigh": "US", "salt lake city": "US", "salt": "US",
    "san francisco": "US", "seattle": "US", "spain": "ES",
    "stockholm": "SE", "switzerland": "CH", "tallinn": "EE",
    "uk": "UK", "vienna": "AT", "washington": "US", "zurich": "CH",
    # India hubs
    "bangalore": "IN", "bengaluru": "IN", "mumbai": "IN", "pune": "IN",
    "delhi": "IN", "new delhi": "IN", "gurgaon": "IN", "gurugram": "IN",
    "noida": "IN", "hyderabad": "IN", "chennai": "IN", "kolkata": "IN",
    "ahmedabad": "IN",
}

SWISS_LOCATION_TERMS = [
    "switzerland", "schweiz", "suisse", "svizzera", "swiss",
    "zurich", "geneva", "geneve", "lausanne", "lausane",
    "basel", "bern", "zug", "lucerne", "luzern",
    "winterthur", "ticino", "st gallen", "st. gallen",
]

TITLE_SYNONYMS: Dict[str, str] = {
    "swe": "software engineer", "software eng": "software engineer",
    "sw eng": "software engineer", "frontend": "front end",
    "front-end": "front end", "backend": "back end", "back-end": "back end",
    "fullstack": "full stack", "full-stack": "full stack",
    "pm": "product manager", "prod mgr": "product manager",
    "product owner": "product manager", "ds": "data scientist",
    "ml": "machine learning", "mle": "machine learning engineer",
    "sre": "site reliability engineer", "devops": "devops",
    "sec eng": "security engineer", "infosec": "security",
    "programmer": "developer", "coder": "developer",
    # Spanish (and similar) — curated titles are mostly English; map to shared tokens.
    "ingenieros": "engineer", "ingeniero": "engineer", "ingeniera": "engineer",
    "desarrolladores": "developer", "desarrollador": "developer", "desarrolladora": "developer",
}


def normalize_country(q: str) -> str:
    """Return normalized country code for a query string."""
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
    """Normalize a job title query string."""
    if not q:
        return ""
    s = q.lower().strip()
    # Longest keys first; word-boundary replace so e.g. "software eng" does not corrupt "software engineer".
    for k, v in sorted(TITLE_SYNONYMS.items(), key=lambda kv: -len(kv[0])):
        if not k.strip():
            continue
        pat = r"\b" + re.escape(k) + r"\b"
        s = re.sub(pat, v, s, flags=re.IGNORECASE)
    s = re.sub(r"[^\w\s\-\/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ============================================================================
# ── Link blacklist (demo / test fixtures) ─────────────────────────────────────
# ============================================================================

BLACKLIST_LINKS = {
    "https://example.com/job/1",
}


# ============================================================================
# ── Flask route helpers ───────────────────────────────────────────────────────
# ============================================================================


def csrf_valid() -> bool:
    """Validate CSRF token from form data or headers against session token."""
    expected = str(session.get("_csrf_token") or "")
    provided = (
        request.form.get("csrf_token")
        or request.headers.get("X-CSRF-Token")
        or ""
    ).strip()
    if not expected or not provided:
        return False
    return secrets.compare_digest(expected, provided)


def resolve_pagination(default_per_page: int = 12) -> Tuple[int, int]:
    """Return (page, per_page_limit) constrained to safe bounds."""
    per_page = parse_int_arg(
        request.args,
        "per_page",
        default=default_per_page,
        minimum=1,
        maximum=int(current_app.config.get("PER_PAGE_MAX", PER_PAGE_MAX)),
    )
    page = parse_int_arg(request.args, "page", default=1, minimum=1, maximum=10_000)
    return page, per_page


def api_error_response(code: str, message: str, status: int = 400, details: Optional[Dict[str, Any]] = None):
    """Return a standardised JSON API error response."""
    return jsonify(
        api_fail(
            code=code,
            message=message,
            request_id=getattr(g, "request_id", ""),
            details=details or {},
        )
    ), status


def api_success_response(data: Dict[str, Any], status: int = 200, code: str = "ok", message: str = "ok"):
    """Return a standardised JSON API success response."""
    return jsonify(
        api_ok(
            data=data,
            request_id=getattr(g, "request_id", ""),
            code=code,
            message=message,
        )
    ), status


def require_api_key(f):
    """Decorator: validate X-API-Key header, enforce daily quota, inject rate-limit headers."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        raw_key = (
            request.headers.get("X-API-Key")
            or request.args.get("api_key")
            or ""
        ).strip()
        if not raw_key:
            return api_error_response("invalid_key", "A valid API key is required.", 401)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        from .models.api_keys import check_and_increment_api_key  # noqa: PLC0415
        usage = check_and_increment_api_key(key_hash, now)
        if usage is None:
            return api_error_response("invalid_key", "Invalid or revoked API key.", 401)
        if isinstance(usage, dict) and usage.get("error") == "quota_exceeded":
            return api_error_response(
                "quota_exceeded",
                "API quota exceeded for this key.",
                429,
                details={"window": usage.get("window", "daily")},
            )
        g.api_key_record = usage

        @after_this_request
        def _inject_ratelimit_headers(response):
            rec = g.get("api_key_record", {})
            limit = rec.get("daily_limit", 50)
            used = rec.get("requests_today", 0)
            _now = datetime.now(timezone.utc)
            reset_dt = (_now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(max(0, limit - used))
            response.headers["X-RateLimit-Reset"] = reset_dt.isoformat()
            response.headers["X-RateLimit-Window"] = "daily"
            return response

        return f(*args, **kwargs)
    return decorated



# ============================================================================
# ── Guest daily job-view limit (merged from controllers/jobs.py) ─────────────
# ============================================================================


def guest_daily_remaining() -> int:
    """Return remaining guest job views for today. -1 means unlimited (signed in or subscribed)."""
    if session.get("user") or session.get("subscribed"):
        return -1
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if session.get("_guest_date") != today:
        session["_guest_date"] = today
        session["_guest_seen"] = 0
        session.modified = True
    return max(0, GUEST_DAILY_LIMIT - int(session.get("_guest_seen") or 0))


def guest_daily_consume(count: int) -> None:
    """Record that `count` jobs were shown to a guest today."""
    if session.get("user") or session.get("subscribed"):
        return
    session["_guest_seen"] = int(session.get("_guest_seen") or 0) + count
    session.modified = True


# ── Public API ────────────────────────────────────────────────────────────────
# ============================================================================

__all__ = [
    # Cache
    "TTLCache",
    "SUMMARY_CACHE",
    "AUTOCOMPLETE_CACHE",
    "SALARY_CACHE",
    # API response helpers
    "generate_request_id",
    "api_ok",
    "api_fail",
    "parse_int_arg",
    "parse_str_arg",
    # Pure utilities
    "slugify",
    "slugify_job_title",
    "to_lc",
    "coerce_datetime",
    "job_is_new",
    "job_is_ghost",
    "now_iso",
    # Email validation
    "EmailNotValidError",
    "validate_email",
    "disposable_email_domain",
    # Normalization
    "COUNTRY_NORM",
    "LOCATION_COUNTRY_HINTS",
    "SWISS_LOCATION_TERMS",
    "TITLE_SYNONYMS",
    "normalize_country",
    "normalize_title",
    # Link blacklist
    "BLACKLIST_LINKS",
    # Flask route helpers
    "csrf_valid",
    "resolve_pagination",
    "api_error_response",
    "api_success_response",
    "require_api_key",
    # Guest limits
    "guest_daily_remaining",
    "guest_daily_consume",
]
