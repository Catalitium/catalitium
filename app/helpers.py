"""Shared helpers used across multiple route modules.

Extracted from app.py to avoid duplication when routes are split into blueprints.
"""

import functools
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from flask import (
    after_this_request,
    current_app,
    g,
    jsonify,
    request,
    session,
)

from .api_utils import api_fail, api_ok, parse_int_arg
from .config import GHOST_JOB_DAYS, PER_PAGE_MAX
from .models.db import (
    _compact_salary_number,
    check_and_increment_api_key,
    logger,
    salary_range_around,
)

# ---------------------------------------------------------------------------
# Title-seniority keywords used for salary uplift estimation
# ---------------------------------------------------------------------------
TITLE_BUCKET2_KEYWORDS = (
    "principal",
    "staff",
    "lead ",
    "lead-",
    "head of",
    "director",
)

TITLE_BUCKET1_KEYWORDS = (
    "senior",
    "sr ",
    "sr.",
    "expert",
)

BLACKLIST_LINKS = {
    "https://example.com/job/1",
}

# ---------------------------------------------------------------------------
# Salary seed data (DACH reference percentiles)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Pure utility functions
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Convert text to a URL-safe slug (max 60 chars)."""
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:60]


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
    formats = ("%Y-%m-%d", "%Y.%m.%d", "%Y%m%d", "%Y/%m/%d")
    for fmt in formats:
        try:
            dt = datetime.strptime(text[: len(fmt)], fmt)
            return dt
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
    now = datetime.now(timezone.utc)
    return (now - dt) <= timedelta(days=7)


def job_is_ghost(job_date_raw) -> bool:
    """Return True when the job was posted more than GHOST_JOB_DAYS ago (may be filled)."""
    dt = coerce_datetime(job_date_raw)
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt) > timedelta(days=GHOST_JOB_DAYS)


def to_lc(value: str) -> str:
    """Return a lowercase camel-style version of a string for API responses."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", value or "") if p]
    if not parts:
        return value or ""
    head, *tail = parts
    return head.lower() + "".join(part.capitalize() for part in tail)


def estimate_salary_display(
    title: str,
    median: float,
) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Compute estimated salary range string and min/max for a given title and median.

    Returns (display_string, sal_min, sal_max) or (None, None, None) on failure.
    """
    try:
        title_lc = title.lower()
        uplift = 1.10 if any(k in title_lc for k in TITLE_BUCKET2_KEYWORDS) else (
            1.05 if any(k in title_lc for k in TITLE_BUCKET1_KEYWORDS) else 1.0)
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


# ---------------------------------------------------------------------------
# Flask-context helpers (use Flask proxies; safe for blueprint imports)
# ---------------------------------------------------------------------------

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
