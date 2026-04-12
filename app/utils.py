"""app/utils.py — Single utility surface for Catalitium.

Merges: api_utils, helpers, normalization, spam_guards, subscriber_fields.
Named TTL caches at module level (A2). Canonical now_iso (R2). Merged
validate_email+disposable (R3). Explicit __all__ (E2).
"""

from __future__ import annotations

# ── stdlib ──────────────────────────────────────────────────────────────────
import functools
import hashlib
import json
import logging
import re
import secrets
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

# ── Flask (proxies; safe for blueprint-level imports) ────────────────────────
from flask import after_this_request, current_app, g, jsonify, request, session

# ── App config ───────────────────────────────────────────────────────────────
from .config import (
    AUTOCOMPLETE_CACHE_MAX,
    AUTOCOMPLETE_CACHE_TTL,
    GHOST_JOB_DAYS,
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
    _path = Path(__file__).parent / "models" / "country_norm.json"
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
    s = q.lower()
    for k, v in TITLE_SYNONYMS.items():
        if k in s:
            s = s.replace(k, v)
    s = re.sub(r"[^\w\s\-\/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ============================================================================
# ── Spam & validation ─────────────────────────────────────────────────────────
# ============================================================================

# Must match `snippets/_honeypot_field.html` name= attribute.
HONEYPOT_FIELD = "hp_company_url"

_MAX_CONTACT_NAME = 120
_MAX_CONTACT_MESSAGE = 1200
_URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)


def _payload_get(payload: Mapping[str, Any], key: str) -> str:
    try:
        v = payload.get(key)
    except Exception:
        return ""
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    return str(v).strip()


def honeypot_triggered(payload: Mapping[str, Any]) -> bool:
    """True when the honeypot field is non-empty (typical bot behavior)."""
    return bool(_payload_get(payload, HONEYPOT_FIELD))


def _too_many_links(text: str, max_links: int = 5) -> bool:
    return len(_URL_RE.findall(text or "")) > max_links


def _only_urls(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    remainder = _URL_RE.sub("", t)
    remainder = re.sub(r"\s+", "", remainder)
    return len(remainder) == 0


def _repetition_spam(s: str) -> bool:
    s2 = "".join(c for c in (s or "").lower() if c.isalnum())
    if len(s2) < 16:
        return False
    top = Counter(s2).most_common(1)[0][1]
    return (top / len(s2)) >= 0.55


def prepare_contact_submission(name: str, message: str) -> Optional[Tuple[str, str]]:
    """Return (name, message) ready for INSERT, or None if spam."""
    n = (name or "").strip()
    m = (message or "").strip()
    if len(n) > _MAX_CONTACT_NAME:
        n = n[:_MAX_CONTACT_NAME].strip()
    if len(m) > _MAX_CONTACT_MESSAGE:
        m = m[:_MAX_CONTACT_MESSAGE].strip()
    low_msg = m.lower()
    low_name = n.lower()
    if "<script" in low_msg or "<script" in low_name:
        return None
    if _too_many_links(m) or _only_urls(m):
        return None
    if _repetition_spam(m) or _repetition_spam(n):
        return None
    return (n, m)


# ============================================================================
# ── Subscriber field sanitization ─────────────────────────────────────────────
# ============================================================================

VOWELS = frozenset("aeiouy")

_TITLE_MARKERS = frozenset({
    "eng", "soft", "data", "dev", "ops", "ml", "ai", "pm", "ux", "ui",
    "product", "manage", "design", "analyst", "architect", "scientist",
    "engineer", "developer", "research", "consult", "director", "lead",
    "senior", "junior", "principal", "staff", "intern", "recruit", "market",
    "finance", "security", "cloud", "network", "mobile", "full", "backend",
    "frontend", "stack", "machine", "learning", "sales", "support", "quality",
    "writer", "content", "business", "account", "customer", "success",
    "growth", "founder", "executive", "head", "chief", "java", "python",
    "rust", "ruby", "scala", "node", "react", "vue", "angular", "swift",
    "kotlin", "kubernetes", "docker", "aws", "azure", "linux", "dba",
    "oracle", "etl", "direct",
})

_SALARY_SIGNAL = re.compile(
    r"[0-9]|[$€£]|chf|eur|usd|gbp|\d\s*[-–]\s*\d|[-–]\s*\d|\d\s*k\b",
    re.IGNORECASE,
)


def _max_consonant_run(s: str) -> int:
    best = cur = 0
    for ch in s.lower():
        if ch.isalpha() and ch not in VOWELS:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _vowel_ratio(s: str) -> float:
    if not s:
        return 0.0
    v = sum(1 for c in s.lower() if c in VOWELS)
    return v / len(s)


def _country_from_location_hints(raw_lower: str) -> str:
    if not raw_lower:
        return ""
    for token, code in sorted(LOCATION_COUNTRY_HINTS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if token in raw_lower:
            c = (code or "").strip().upper()
            if len(c) == 2 and c.isalpha():
                return c
    return ""


def _country_from_norm_keys(raw_lower: str) -> str:
    for key, code in sorted(COUNTRY_NORM.items(), key=lambda kv: len(kv[0]), reverse=True):
        if key in raw_lower:
            c = (code or "").strip().upper()
            if len(c) == 2 and c.isalpha():
                return c
    return ""


def sanitize_search_title(raw: str, *, max_len: int = 160) -> str:
    s = normalize_title(raw or "").strip()
    if not s:
        return ""
    if len(s) > max_len:
        s = s[:max_len].strip()
    if any(c.isdigit() for c in s):
        return s
    if any(ch in s for ch in (" ", ",", "/", "&", "(", ")", "-", "–")):
        return s
    low = s.lower()
    if any(tok in low for tok in _TITLE_MARKERS):
        return s
    if len(low) <= 5:
        return s
    if not re.fullmatch(r"[a-z]+", low):
        return s
    if _vowel_ratio(low) < 0.3:
        return ""
    if _max_consonant_run(low) >= 5:
        return ""
    return s


def sanitize_search_country(raw: str) -> str:
    raw_s = (raw or "").strip()
    if not raw_s:
        return ""
    n = normalize_country(raw_s)
    t = (n or "").strip()
    if len(t) == 2 and t.isalpha():
        return t.upper()
    low = raw_s.lower()
    hint = _country_from_location_hints(low)
    if hint:
        return hint
    return _country_from_norm_keys(low)


def sanitize_search_salary_band(raw: str, *, max_len: int = 80) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if len(s) > max_len:
        s = s[:max_len].strip()
    if _SALARY_SIGNAL.search(s):
        return s
    low = s.lower()
    if re.fullmatch(r"[a-z]+", low) and len(low) >= 6:
        return ""
    return s


def sanitize_subscriber_search_fields(
    search_title: str,
    search_country: str,
    search_salary_band: str,
) -> tuple[str, str, str]:
    """Return cleaned (title, country, salary_band) safe to persist."""
    return (
        sanitize_search_title(search_title),
        sanitize_search_country(search_country),
        sanitize_search_salary_band(search_salary_band),
    )


# ============================================================================
# ── Salary helpers (R4: helpers.py estimate functions) ───────────────────────
# ============================================================================

TITLE_BUCKET2_KEYWORDS = (
    "principal", "staff", "lead ", "lead-", "head of", "director",
)

TITLE_BUCKET1_KEYWORDS = (
    "senior", "sr ", "sr.", "expert",
)

BLACKLIST_LINKS = {
    "https://example.com/job/1",
}

_SALARY_SEED: dict[tuple[str, str], dict] = {
    ("engineer", "zurich"):  {"p25": 110_000, "p50": 130_000, "p75": 155_000, "currency": "CHF"},
    ("engineer", "geneva"):  {"p25": 105_000, "p50": 125_000, "p75": 148_000, "currency": "CHF"},
    ("engineer", "basel"):   {"p25": 100_000, "p50": 118_000, "p75": 140_000, "currency": "CHF"},
    ("engineer", "berlin"):  {"p25":  65_000, "p50":  82_000, "p75": 100_000, "currency": "EUR"},
    ("engineer", "munich"):  {"p25":  72_000, "p50":  90_000, "p75": 110_000, "currency": "EUR"},
    ("engineer", "vienna"):  {"p25":  58_000, "p50":  72_000, "p75":  88_000, "currency": "EUR"},
    ("product",  "zurich"):  {"p25": 105_000, "p50": 125_000, "p75": 148_000, "currency": "CHF"},
    ("product",  "geneva"):  {"p25": 100_000, "p50": 120_000, "p75": 142_000, "currency": "CHF"},
    ("product",  "berlin"):  {"p25":  62_000, "p50":  78_000, "p75":  96_000, "currency": "EUR"},
    ("product",  "munich"):  {"p25":  68_000, "p50":  85_000, "p75": 104_000, "currency": "EUR"},
    ("data",     "zurich"):  {"p25": 108_000, "p50": 128_000, "p75": 152_000, "currency": "CHF"},
    ("data",     "berlin"):  {"p25":  60_000, "p50":  76_000, "p75":  94_000, "currency": "EUR"},
    ("data",     "munich"):  {"p25":  65_000, "p50":  82_000, "p75": 100_000, "currency": "EUR"},
    ("design",   "zurich"):  {"p25":  90_000, "p50": 108_000, "p75": 128_000, "currency": "CHF"},
    ("design",   "berlin"):  {"p25":  52_000, "p50":  66_000, "p75":  82_000, "currency": "EUR"},
    ("devops",   "zurich"):  {"p25": 112_000, "p50": 132_000, "p75": 158_000, "currency": "CHF"},
    ("devops",   "berlin"):  {"p25":  68_000, "p50":  85_000, "p75": 104_000, "currency": "EUR"},
    ("manager",  "zurich"):  {"p25": 120_000, "p50": 145_000, "p75": 175_000, "currency": "CHF"},
    ("manager",  "berlin"):  {"p25":  75_000, "p50":  95_000, "p75": 118_000, "currency": "EUR"},
}

_DACH_CHF_CITIES = ("zurich", "geneva", "basel")


def get_salary_percentiles(title: str, location: str) -> dict:
    """Return P25/P50/P75 from seed data; fall back to generic DACH estimates."""
    loc = location.lower()
    title_lower = title.lower()
    for (kw, city), data in _SALARY_SEED.items():
        if city in loc and kw in title_lower:
            return data
    currency = "CHF" if any(c in loc for c in _DACH_CHF_CITIES) else "EUR"
    return {"p25": 70_000, "p50": 90_000, "p75": 115_000, "currency": currency}


def estimate_salary_display(
    title: str,
    median: float,
) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Compute estimated salary range string and min/max for a given title and median.

    Uses deferred import to avoid circular imports at module load time.
    Returns (display_string, sal_min, sal_max) or (None, None, None) on failure.
    """
    try:
        from .models.db import _compact_salary_number, salary_range_around  # noqa: PLC0415
        title_lc = title.lower()
        uplift = (
            1.10 if any(k in title_lc for k in TITLE_BUCKET2_KEYWORDS) else
            1.05 if any(k in title_lc for k in TITLE_BUCKET1_KEYWORDS) else
            1.0
        )
        base_rng = salary_range_around(float(median), pct=0.2)
        if not base_rng:
            return None, None, None
        base_low, base_high, base_low_s, base_high_s = base_rng
        if uplift > 1.0:
            amt = float(median) * (uplift - 1.0)
            low_s = _compact_salary_number(base_low + amt)
            high_s = _compact_salary_number(base_high + amt)
            return f"{low_s}\u2013{high_s}", int(base_low + amt), int(base_high + amt)
        return f"{base_low_s}\u2013{base_high_s}", base_low, base_high
    except Exception:
        return None, None, None


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
            return jsonify({"error": "invalid_key"}), 401
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        from .models.identity import check_and_increment_api_key  # noqa: PLC0415
        usage = check_and_increment_api_key(key_hash, now)
        if usage is None:
            return jsonify({"error": "invalid_key"}), 401
        if isinstance(usage, dict) and usage.get("error") == "quota_exceeded":
            return jsonify({
                "error": "quota_exceeded",
                "window": usage.get("window", "daily"),
            }), 429
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
    # Spam & validation
    "HONEYPOT_FIELD",
    "honeypot_triggered",
    "prepare_contact_submission",
    # Subscriber sanitization
    "sanitize_search_title",
    "sanitize_search_country",
    "sanitize_search_salary_band",
    "sanitize_subscriber_search_fields",
    # Salary helpers
    "TITLE_BUCKET1_KEYWORDS",
    "TITLE_BUCKET2_KEYWORDS",
    "BLACKLIST_LINKS",
    "_SALARY_SEED",
    "get_salary_percentiles",
    "estimate_salary_display",
    # Flask route helpers
    "csrf_valid",
    "resolve_pagination",
    "api_error_response",
    "api_success_response",
    "require_api_key",
]
