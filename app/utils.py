"""app/utils.py — Single utility surface for Catalitium.

Sections (in order):
  TTL caches · API response helpers · Pure utilities · Email validation
  Normalization · Spam guards · Subscriber sanitization · Salary helpers
  Flask route helpers (CSRF, pagination, rate-limit decorator)
  Mailer — all outbound SMTP email          (merged from mailer.py)
  REPORTS — market reports catalog          (merged from market_reports_data.py)
  DEMO_JOBS — fallback job list             (inlined from app/data/demo_jobs.csv)
  guest_daily_remaining/consume             (promoted from controllers/jobs.py)
  run_weekly_digest()                       (merged from scripts/send_weekly_digest.py)
  validate_market_reports()                 (merged from scripts/validate_market_reports.py)
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
from collections import Counter
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
        from .models.money import _compact_salary_number, salary_range_around  # noqa: PLC0415
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
# ── Market reports catalog (merged from app/market_reports_data.py) ──────────
# ============================================================================

REPORTS = [
    {
        "slug": "global-tech-ai-careers-report-2026",
        "title": "Catalitium Global Tech & AI Careers Report - 2026 Edition",
        "short_title": "Global Tech & AI Careers Report 2026",
        "description": (
            "Data-driven analysis of AI's impact on tech jobs, skills in demand, "
            "salaries by region (US, Europe, India), and the fastest growing roles for 2025-2026."
        ),
        "published": "2025-11-01",
        "published_display": "November 2025",
        "pdf_path": "reports/R01- Catalitium Global Tech & AI Careers Report  November 2025 Edition.pdf",
        "read_time": "12 min read",
        "keywords": [
            "global tech and AI jobs report 2026",
            "AI careers report 2026",
            "tech skills in demand 2025",
            "AI job market trends",
            "2025 tech salaries US Europe India",
            "remote and hybrid work trends in tech",
            "fastest growing AI jobs 2025 2026",
        ],
    },
    {
        "slug": "aaas-tipping-point-saas-economics-2026",
        "title": "The AaaS Tipping Point: Why AI Agents Are Killing SaaS Economics in 2026",
        "short_title": "The AaaS Tipping Point Report 2026",
        "description": (
            "Whether Agents as a Service can capture 30%+ of enterprise software spend by 2028: "
            "Gartner, IDC, McKinsey, and workflow-level TCO evidence on agentic AI vs. seat-based SaaS. "
            "37 sources, April 2026."
        ),
        "published": "2026-03-01",
        "published_display": "March 2026",
        "pdf_path": "",
        "read_time": "22 min read",
        "gated": True,
        "template": "reports/aaas_tipping_point.html",
        "keywords": [
            "AaaS agents as a service 2026",
            "AI agents vs SaaS economics",
            "enterprise software spend agentic AI",
            "Gartner agentic AI enterprise applications",
            "SaaS TCO vs AI agents",
            "Automation Anywhere AI service agents",
            "LangGraph pricing per action",
            "Fortune 500 AI agents production 2026",
        ],
    },
    {
        "slug": "ai-skill-premium-index-2026",
        "title": "The AI Skill Premium Index 2026: Which AI Skills Command the Highest Salary Premiums",
        "short_title": "AI Skill Premium Index 2026",
        "description": (
            "Lightcast, Levels.fyi, Pave, and SignalFire data on AI vs SWE pay: ~28% posting premium, "
            "43% with 2+ AI skills, LLM and safety specializations, myths vs reality. February 2026."
        ),
        "published": "2026-02-15",
        "published_display": "February 2026",
        "pdf_path": "",
        "read_time": "18 min read",
        "gated": True,
        "template": "reports/ai_skill_premium_index_2026.html",
        "keywords": [
            "AI skill salary premium 2026",
            "LLM engineer compensation vs ML engineer",
            "Lightcast AI job postings premium",
            "Levels.fyi AI engineer salary 2025",
            "MLOps salary premium",
            "AI safety alignment salary growth",
            "tech compensation Big Tech AI vs SWE",
        ],
    },
    {
        "slug": "european-llm-build-vs-buy-2026",
        "title": "From Build to Buy: How the LLM Platform Era Is Rewriting Software Economics (Europe)",
        "short_title": "European LLM Build vs Buy Report 2026",
        "description": (
            "Europe enterprise LLM market ~$1.09B, 76% of AI now purchased vs built, EU AI Act compliance costs, "
            "API pricing tiers, and talent benchmarks. 20+ sources, February 2026."
        ),
        "published": "2026-02-01",
        "published_display": "February 2026",
        "pdf_path": "",
        "read_time": "24 min read",
        "gated": True,
        "template": "reports/european_llm_build_buy_2026.html",
        "keywords": [
            "Europe LLM market 2026",
            "build vs buy enterprise AI Europe",
            "EU AI Act compliance cost SME",
            "Menlo Ventures AI purchased vs built",
            "European SaaS LLM API economics",
            "AI engineer salary Europe Switzerland Spain",
            "LLM API pricing comparison 2025",
        ],
    },
    {
        "slug": "200k-engineer-ai-reshaping-software-salaries-2026",
        "title": "The $200K Engineer: How AI Productivity Is Reshaping Software Salaries",
        "short_title": "The $200K Engineer Report 2026",
        "description": (
            "Staff engineers saw 7.52% comp growth while junior hiring collapsed 73%. "
            "A data-driven investigation into who wins, who loses, and what drives the split "
            "in software engineering compensation in 2025\u20132026. 69 sources."
        ),
        "published": "2026-02-01",
        "published_display": "February 2026",
        "pdf_path": "",
        "read_time": "18 min read",
        "gated": True,
        "template": "reports/200k_engineer.html",
        "keywords": [
            "software engineer salary 2026",
            "AI skills salary premium",
            "staff engineer compensation growth",
            "junior developer hiring collapse 2025",
            "AI productivity compensation bifurcation",
            "Anthropic OpenAI engineer salary",
            "revenue per employee software companies",
            "software engineering salary trends 2026",
        ],
    },
    {
        "slug": "from-saas-to-agents-ai-native-workforce-2026",
        "title": "From SaaS to Agents: How AI Native Software Is Reshaping the Tech Workforce",
        "short_title": "From SaaS to Agents Report 2026",
        "description": (
            "A data-driven investigation into team economics, revenue per employee, AI-agent adoption, "
            "and the structural transformation of software work. 74 sources, February 2026."
        ),
        "published": "2026-02-01",
        "published_display": "February 2026",
        "pdf_path": "",
        "read_time": "20 min read",
        "gated": True,
        "template": "reports/saas_to_agents.html",
        "keywords": [
            "AI native software workforce 2026",
            "revenue per employee AI companies",
            "SaaS to agents transition",
            "AI engineer hiring demand 2026",
            "software developer job market decline",
            "GitHub Copilot productivity study",
            "enterprise AI adoption transformation gap",
            "Klarna AI workforce case study",
        ],
    },
    {
        "slug": "ai-productivity-paradox-junior-roles-2026",
        "title": "AI Didn\u2019t Kill Jobs \u2014 It Killed Junior Roles",
        "short_title": "AI Productivity Paradox Report 2026",
        "description": (
            "Entry-level tech job postings dropped 35% since 2023 while AI engineers earn $206K on average. "
            "Data-driven analysis of how AI productivity tools are reshaping the tech labor market, "
            "collapsing junior demand, and creating an unprecedented senior skill premium."
        ),
        "published": "2025-12-01",
        "published_display": "December 2025",
        "pdf_path": "reports/R02- AI Didn\u2019t Kill Jobs \u2014 It Killed Junior Roles.pdf",
        "read_time": "15 min read",
        "gated": True,
        "template": "reports/junior_roles.html",
        "keywords": [
            "entry level tech jobs 2026",
            "AI productivity paradox",
            "junior developer jobs decline",
            "AI skill salary premium 2025",
            "tech hiring trends 2026",
            "github copilot adoption stats",
            "series A team size decline",
            "CS degree unemployment 2025",
        ],
    },
    {
        "slug": "death-of-saas-vibecoding-2026",
        "title": "The Death of SaaS: How Vibecoding Is Killing a $315 Billion Industry",
        "short_title": "The Death of SaaS Report 2026",
        "description": (
            "A data-driven market report analyzing how AI-assisted development is structurally "
            "disrupting the $315 billion SaaS industry, with sourced data from a16z, Gartner, "
            "YC, Retool, Deloitte, and Emergence Capital."
        ),
        "published": "2026-02-01",
        "published_display": "February 2026",
        "pdf_path": "reports/R03- The Death of SaaS How Vibecoding Is Killing a 315 Billion Industry.pdf",
        "read_time": "18 min read",
        "gated": True,
        "template": "reports/saas_vibecoding.html",
        "keywords": [
            "death of saas 2026",
            "vibecoding saas disruption",
            "ai coding tools market report",
            "build vs buy saas 2026",
            "saas market size 2026",
            "cursor ai growth",
            "ai native saas vs traditional saas",
            "software as labor business model",
        ],
    },
]


# ============================================================================
# ── Demo jobs (inlined from app/data/demo_jobs.csv) ──────────────────────────
# ============================================================================

DEMO_JOBS: list[dict] = [
    {
        "id": "demo-1", "title": "Senior Software Engineer (AI)", "company": "Catalitium",
        "location": "Remote / EU",
        "description": "Own end-to-end features across ingestion and ranking and AI-assisted matching.",
        "date_posted": "2025.10.01", "date_raw": "", "link": "", "is_new": False, "is_ghost": False,
        "match_score": None, "match_reasons": [], "median_salary": None, "median_salary_currency": None,
        "median_salary_compact": None, "estimated_salary_range_compact": None,
        "estimated_salary_range_numeric": None, "salary_delta_pct": None, "salary_uplift_factor": None,
    },
    {
        "id": "demo-2", "title": "Data Engineer", "company": "Catalitium",
        "location": "London UK",
        "description": "Build reliable pipelines and optimize warehouse performance.",
        "date_posted": "2025.09.28", "date_raw": "", "link": "", "is_new": False, "is_ghost": False,
        "match_score": None, "match_reasons": [], "median_salary": None, "median_salary_currency": None,
        "median_salary_compact": None, "estimated_salary_range_compact": None,
        "estimated_salary_range_numeric": None, "salary_delta_pct": None, "salary_uplift_factor": None,
    },
    {
        "id": "demo-3", "title": "Product Manager", "company": "Stealth",
        "location": "Zurich CH",
        "description": "Partner with design and engineering to deliver user value quickly.",
        "date_posted": "2025.09.27", "date_raw": "", "link": "", "is_new": False, "is_ghost": False,
        "match_score": None, "match_reasons": [], "median_salary": None, "median_salary_currency": None,
        "median_salary_compact": None, "estimated_salary_range_compact": None,
        "estimated_salary_range_numeric": None, "salary_delta_pct": None, "salary_uplift_factor": None,
    },
    {
        "id": "demo-4", "title": "Frontend Developer", "company": "Acme Corp",
        "location": "Barcelona ES",
        "description": "Ship delightful UI with Tailwind and strong accessibility.",
        "date_posted": "2025.09.26", "date_raw": "", "link": "", "is_new": False, "is_ghost": False,
        "match_score": None, "match_reasons": [], "median_salary": None, "median_salary_currency": None,
        "median_salary_compact": None, "estimated_salary_range_compact": None,
        "estimated_salary_range_numeric": None, "salary_delta_pct": None, "salary_uplift_factor": None,
    },
    {
        "id": "demo-5", "title": "Cloud DevOps Engineer", "company": "Nimbus",
        "location": "Remote / Europe",
        "description": "Automate infrastructure and observability and release workflows.",
        "date_posted": "2025.09.25", "date_raw": "", "link": "", "is_new": False, "is_ghost": False,
        "match_score": None, "match_reasons": [], "median_salary": None, "median_salary_currency": None,
        "median_salary_compact": None, "estimated_salary_range_compact": None,
        "estimated_salary_range_numeric": None, "salary_delta_pct": None, "salary_uplift_factor": None,
    },
    {
        "id": "demo-6", "title": "ML Engineer", "company": "Quantix",
        "location": "Remote",
        "description": "Deploy ranking and semantic matching at scale.",
        "date_posted": "2025.09.24", "date_raw": "", "link": "", "is_new": False, "is_ghost": False,
        "match_score": None, "match_reasons": [], "median_salary": None, "median_salary_currency": None,
        "median_salary_compact": None, "estimated_salary_range_compact": None,
        "estimated_salary_range_numeric": None, "salary_delta_pct": None, "salary_uplift_factor": None,
    },
]


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


# ============================================================================
# ── Mailer (merged from app/mailer.py) ───────────────────────────────────────
# ============================================================================


def _base_url() -> str:
    return os.getenv("BASE_URL", "https://catalitium.com").rstrip("/")


def _send_mail(to: str, subject: str, body: str) -> None:
    """Send a plain-text email via SMTP. Best-effort; logs on failure, never raises."""
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    pw = os.getenv("SMTP_PASS", "").strip()
    frm = os.getenv("SMTP_FROM", "noreply@catalitium.com").strip()
    if not host:
        logger.warning("_send_mail: SMTP_HOST not configured, skipping email to %s", to)
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = frm
        msg["To"] = to
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            if user:
                s.login(user, pw)
            s.send_message(msg)
    except Exception as exc:
        logger.warning("_send_mail failed (to=%s): %s", to, exc)


def send_subscribe_welcome(email: str, focus: str = "") -> None:
    """Send a welcome confirmation email to a new subscriber."""
    focus_line = f"\nYour focus: {focus}\n" if focus else ""
    body = f"""Welcome to Catalitium.

You're now on the weekly high-match digest.{focus_line}
Every week we send you the highest-signal tech jobs with real salary data: no noise, no spam.

Browse jobs now: {_base_url()}

--
Catalitium | info@catalitium.com
Unsubscribe: {_base_url()}/unsubscribe
"""
    _send_mail(email, "You're on the Catalitium weekly digest", body)


def send_api_key_activation(email: str, raw_key: str, confirm_url: str) -> None:
    """Send API key details to a new free-tier registrant (needs email confirmation)."""
    body = (
        f"Hello,\n\n"
        f"Your Catalitium API key is:\n\n"
        f"  {raw_key}\n\n"
        f"To activate it, visit the link below (valid 24 hours):\n\n"
        f"  {confirm_url}\n\n"
        f"Once activated, include it in API requests with the header:\n"
        f"  X-API-Key: {raw_key}\n\n"
        f"Free tier: 50 requests/day and 500 per calendar month after activation.\n\n"
        f"-- Catalitium Team"
    )
    _send_mail(email, "Activate your Catalitium API key", body)


def send_api_access_key_provisioned(email: str, raw_key: str, confirm_url: str) -> None:
    """Send API key details after an API Access subscription is activated via Stripe."""
    body = (
        "Your Catalitium API Access subscription is active.\n\n"
        f"Your API key:\n\n  {raw_key}\n\n"
        f"Activate it within 24 hours:\n\n  {confirm_url}\n\n"
        f"Then use header:\n  X-API-Key: {raw_key}\n\n"
        "Included: up to 10,000 successful API calls per calendar month.\n\n"
        "-- Catalitium Team\nhttps://catalitium.com"
    )
    _send_mail(email, "Catalitium API Access — your API key", body)


def send_api_access_payment_confirmed(email: str) -> None:
    """Send receipt to an existing key holder whose API Access subscription renewed."""
    body = (
        "Thanks — your API Access subscription payment was received.\n\n"
        "Your existing API key now includes the paid monthly quota "
        "(10,000 calls per month). Continue using the same key with "
        "header X-API-Key.\n\n"
        f"Manage your plan: {_base_url()}/account/subscription\n\n"
        "-- Catalitium Team"
    )
    _send_mail(email, "Catalitium — API Access payment confirmed", body)


def send_api_key_activation_reminder(email: str, confirm_url: str) -> None:
    """Remind a subscriber with a pending key to activate it after subscribing."""
    body = (
        "Your API Access subscription is active.\n\n"
        "Confirm the API key you registered earlier:\n\n"
        f"  {confirm_url}\n\n"
        "Then use header X-API-Key on /v1/* endpoints.\n\n"
        "-- Catalitium"
    )
    _send_mail(email, "Activate your Catalitium API key (API Access)", body)


def send_job_posting_admin_notification(
    admin_email: str,
    job_title: str,
    company: str,
    plan_name: str,
    user_email: str,
    session_id: str,
    location: str,
    salary_range: str,
    apply_url: str,
    description: str,
) -> None:
    """Notify the admin when a recruiter submits a paid job posting."""
    _send_mail(
        admin_email,
        f"[New Job Posting] {job_title} at {company} ({plan_name})",
        (
            f"Plan: {plan_name}\n"
            f"Paid by: {user_email}\n"
            f"Session: {session_id}\n\n"
            f"Title: {job_title}\n"
            f"Company: {company}\n"
            f"Location: {location or 'Not specified'}\n"
            f"Salary: {salary_range or 'Not specified'}\n"
            f"Apply URL: {apply_url or 'Not specified'}\n\n"
            f"Description:\n{description}"
        ),
    )


def send_job_posting_confirmation(
    user_email: str,
    job_title: str,
    company: str,
    plan_name: str,
) -> None:
    """Confirm to the recruiter that their job posting was received."""
    _send_mail(
        user_email,
        f"Job posting confirmed: {job_title} at {company}",
        (
            f"Hi,\n\nYour job posting has been received and will go live shortly.\n\n"
            f"Plan: {plan_name}\n"
            f"Job title: {job_title}\n"
            f"Company: {company}\n\n"
            f"We'll review and publish it within 24 hours.\n\n"
            f"Thanks,\nThe Catalitium Team\nhttps://catalitium.com"
        ),
    )


# ============================================================================
# ── Weekly digest runner (merged from scripts/send_weekly_digest.py) ─────────
# ============================================================================

DIGEST_JOBS_PER_SEND = 5
_DIGEST_SKIP_DOMAINS: frozenset = frozenset({"checkyourform.xyz"})
_DIGEST_SKIP_EMAILS: frozenset = frozenset({
    "test@gmail.com", "test-qa@catalitium.com", "real-sub-test@catalitium.com",
})


def _digest_fmt_salary(job: dict) -> str:
    sal = (job.get("job_salary_range") or "").strip()
    if sal:
        return sal
    low = job.get("salary_low")
    high = job.get("salary_high")
    if low and high:
        return f"${int(low):,} - ${int(high):,}"
    if low:
        return f"${int(low):,}+"
    return "Salary not listed"


def _digest_job_block(job: dict) -> str:
    base = os.getenv("BASE_URL", "https://catalitium.com").rstrip("/")
    return (
        f"  {job.get('title') or job.get('job_title') or 'Role'}"
        f" at {job.get('company') or 'Company'}\n"
        f"  {job.get('location') or 'Remote'} | {_digest_fmt_salary(job)}\n"
        f"  {job.get('link') or base}\n"
    )


def build_digest_email(subscriber: dict, jobs: list) -> str:
    """Compose the weekly digest email body for one subscriber."""
    base = os.getenv("BASE_URL", "https://catalitium.com").rstrip("/")
    search_title = (subscriber.get("search_title") or "").strip()
    search_country = (subscriber.get("search_country") or "").strip()
    salary_band = (subscriber.get("search_salary_band") or "").strip()
    if search_title and search_country:
        context_line = f"Top {search_title} jobs in {search_country} this week"
    elif search_title:
        context_line = f"Top {search_title} jobs this week"
    elif search_country:
        context_line = f"Top tech jobs in {search_country} this week"
    else:
        context_line = "Top tech jobs this week"
    if salary_band:
        context_line += f" ({salary_band})"
    week = datetime.now(timezone.utc).strftime("%B %d, %Y")
    jobs_text = "\n".join(_digest_job_block(j) for j in jobs)
    return (
        f"Catalitium Weekly Digest - {week}\n"
        f"{context_line}\n"
        f"{'=' * 50}\n\n"
        f"{jobs_text}\n"
        f"Browse all jobs: {base}\n\n"
        f"{'=' * 50}\n"
        f"You're receiving this because you subscribed at catalitium.com.\n"
        f"Unsubscribe: {base}/unsubscribe\n"
    )


def is_real_subscriber(email: str) -> bool:
    """Return False for known test/bot addresses."""
    e = email.strip().lower()
    if e in {s.lower() for s in _DIGEST_SKIP_EMAILS}:
        return False
    return e.split("@")[-1] not in _DIGEST_SKIP_DOMAINS


def run_weekly_digest() -> int:
    """Fetch top jobs and send one digest email per subscriber. Returns exit code."""
    try:
        import psycopg  # noqa: PLC0415
    except ImportError:
        print("[FAIL] psycopg not installed.")
        return 1

    database_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or ""
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").strip()
    smtp_from = os.getenv("SMTP_FROM", "info@catalitium.com").strip()

    print(f"\n=== Catalitium Weekly Digest - {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    if not all([database_url, smtp_host, smtp_user, smtp_pass]):
        print("[FAIL] Missing DATABASE_URL or SMTP config in .env")
        return 1

    conn = psycopg.connect(database_url, autocommit=True)

    def _fetch_subscribers(c) -> list:
        with c.cursor() as cur:
            cur.execute(
                "SELECT email, search_title, search_country, search_salary_band "
                "FROM subscribers ORDER BY created_at"
            )
            cols = ["email", "search_title", "search_country", "search_salary_band"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _fetch_jobs(c, title: str = "", country: str = "", limit: int = DIGEST_JOBS_PER_SEND) -> list:
        clauses, params = [], []
        if title:
            clauses.append("LOWER(job_title) LIKE %s")
            params.append(f"%{title.lower()}%")
        if country:
            clauses.append("LOWER(location) LIKE %s")
            params.append(f"%{country.lower()}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT job_title AS title, company_name AS company, location, "
            f"salary AS job_salary_range, link, job_id AS slug FROM jobs "
            f"{where} ORDER BY date DESC NULLS LAST LIMIT %s"
        )
        params.append(limit)
        with c.cursor() as cur:
            cur.execute(sql, params)
            cols = ["title", "company", "location", "job_salary_range", "link", "slug"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    all_subs = _fetch_subscribers(conn)
    targets = [s for s in all_subs if is_real_subscriber(s["email"])]
    print(f"  Subscribers: {len(all_subs)} total, {len(targets)} real\n")

    try:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        print("  SMTP connected.\n")
    except Exception as exc:
        print(f"  [FAIL] SMTP: {exc}")
        conn.close()
        return 1

    sent = failed = 0
    for sub in targets:
        jobs = _fetch_jobs(conn, title=sub.get("search_title") or "", country=sub.get("search_country") or "")
        if not jobs:
            jobs = _fetch_jobs(conn)
        if not jobs:
            print(f"  [SKIP] {sub['email']} >> no jobs found")
            continue
        body = build_digest_email(sub, jobs)
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = "Catalitium: your weekly tech job digest"
        msg["From"] = f"Catalitium <{smtp_from}>"
        msg["To"] = sub["email"]
        try:
            server.send_message(msg)
            ctx = f"{sub.get('search_title') or ''} {sub.get('search_country') or ''}".strip() or "general"
            print(f"  [SENT] {sub['email']}  ({ctx}, {len(jobs)} jobs)")
            sent += 1
        except Exception as exc:
            print(f"    [FAIL] {sub['email']} >> {exc}")
            failed += 1
        time.sleep(0.5)

    server.quit()
    conn.close()
    print(f"\n=== Done: {sent} sent, {failed} failed ===\n")
    return 0 if failed == 0 else 1


# ============================================================================
# ── Market report validator (merged from scripts/validate_market_reports.py) ──
# ============================================================================


def _report_has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


def _report_has_visuals(text: str) -> bool:
    return len(re.findall(r"<img|<svg|<canvas|chart|plot", text, flags=re.IGNORECASE)) >= 1


def validate_market_reports() -> int:
    """Check each report in REPORTS for template, methodology, sources, visuals, PDF.

    Prints per-report results. Returns exit code (0=all pass, 1=failures found).
    """
    templates_dir = Path(__file__).resolve().parent / "views" / "templates"
    static_dir = Path(__file__).resolve().parent / "static"
    failures: list[str] = []

    print(f"Validating {len(REPORTS)} market research reports...\n")
    for report in REPORTS:
        slug = report.get("slug", "<missing-slug>")
        template_rel = report.get("template", "reports/report.html")
        template_path = templates_dir / template_rel
        pdf_rel = report.get("pdf_path", "")
        pdf_path = static_dir / pdf_rel if pdf_rel else None

        template_exists = template_path.exists()
        template_text = template_path.read_text(encoding="utf-8") if template_exists else ""
        issues: list[str] = []
        if not template_exists:
            issues.append(f"template missing: {template_rel}")
        if not _report_has(r"\bmethodology\b", template_text):
            issues.append("missing methodology section")
        if not _report_has(r"\bsources?\b", template_text):
            issues.append("missing sources section")
        if not _report_has_visuals(template_text):
            issues.append("missing visual markers (svg/img/canvas/chart/plot)")
        if not pdf_rel:
            issues.append("missing pdf_path")
        elif not (pdf_path and pdf_path.exists()):
            issues.append(f"pdf file missing: app/static/{pdf_rel}")

        if issues:
            failures.append(slug)
            print(f"[FAIL] {slug}")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"[OK]   {slug}")
        print()

    if failures:
        print(f"Validation failed: {len(failures)} report(s) need fixes.")
        return 1
    print("Validation passed: all reports meet baseline requirements.")
    return 0


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
    # Market reports
    "REPORTS",
    # Demo jobs
    "DEMO_JOBS",
    # Guest limits
    "guest_daily_remaining",
    "guest_daily_consume",
    # Mailer
    "send_subscribe_welcome",
    "send_api_key_activation",
    "send_api_access_key_provisioned",
    "send_api_access_payment_confirmed",
    "send_api_key_activation_reminder",
    "send_job_posting_admin_notification",
    "send_job_posting_confirmation",
    # Weekly digest
    "DIGEST_JOBS_PER_SEND",
    "build_digest_email",
    "is_real_subscriber",
    "run_weekly_digest",
    # Market report validator
    "validate_market_reports",
]
