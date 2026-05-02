"""Subscriber and contact-form model functions (+ search-field sanitization, honeypot)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping, Optional, Tuple

from ..utils import (
    COUNTRY_NORM,
    LOCATION_COUNTRY_HINTS,
    normalize_country,
    normalize_title,
    now_iso as _now_iso,
)
from .db import get_db, logger, _is_unique_violation

# Must match `partials/_honeypot_field.html` name= attribute.
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


def insert_subscriber(
    email: str,
    search_title: str = "",
    search_country: str = "",
    search_salary_band: str = "",
) -> str:
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO subscribers(email, created_at, search_title, search_country, search_salary_band)
                VALUES(%s, %s, %s, %s, %s)
                """,
                (email, _now_iso(), search_title or None, search_country or None, search_salary_band or None),
            )
        return "ok"
    except Exception as exc:
        if _is_unique_violation(exc):
            return "duplicate"
        logger.warning("insert_subscriber failed: %s", exc, exc_info=True)
        return "error"


def insert_contact(email: str, name_company: str, message: str) -> str:
    db = get_db()
    email_clean = (email or "").strip()
    name_clean = (name_company or "").strip()
    msg_clean = (message or "").strip()
    try:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO contact_form(email, name_company, message, created_at)
                VALUES(%s, %s, %s, %s)
                """,
                (email_clean, name_clean, msg_clean, _now_iso()),
            )
        return "ok"
    except Exception as exc:
        logger.warning("insert_contact failed: %s", exc, exc_info=True)
        return "error"


__all__ = [
    "HONEYPOT_FIELD",
    "honeypot_triggered",
    "insert_contact",
    "insert_subscriber",
    "prepare_contact_submission",
    "sanitize_search_country",
    "sanitize_search_salary_band",
    "sanitize_search_title",
    "sanitize_subscriber_search_fields",
]
