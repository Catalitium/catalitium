"""Server-side cleanup of subscriber digest fields (reduces bot garbage in DB)."""

from __future__ import annotations

import re

from .normalization import (
    COUNTRY_NORM,
    LOCATION_COUNTRY_HINTS,
    normalize_country,
    normalize_title,
)

VOWELS = frozenset("aeiouy")

# Substrings common in real role strings; used to avoid false positives on short tokens.
_TITLE_MARKERS = frozenset(
    {
        "eng",
        "soft",
        "data",
        "dev",
        "ops",
        "ml",
        "ai",
        "pm",
        "ux",
        "ui",
        "product",
        "manage",
        "design",
        "analyst",
        "architect",
        "scientist",
        "engineer",
        "developer",
        "research",
        "consult",
        "director",
        "lead",
        "senior",
        "junior",
        "principal",
        "staff",
        "intern",
        "recruit",
        "market",
        "finance",
        "security",
        "cloud",
        "network",
        "mobile",
        "full",
        "backend",
        "frontend",
        "stack",
        "machine",
        "learning",
        "sales",
        "support",
        "quality",
        "writer",
        "content",
        "business",
        "account",
        "customer",
        "success",
        "growth",
        "founder",
        "executive",
        "head",
        "chief",
        "java",
        "python",
        "rust",
        "ruby",
        "scala",
        "node",
        "react",
        "vue",
        "angular",
        "swift",
        "kotlin",
        "kubernetes",
        "docker",
        "aws",
        "azure",
        "linux",
        "dba",
        "oracle",
        "etl",
        "direct",
    }
)

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
    """Map free-text locations (e.g. Zurich) to ISO2 when country_norm misses them."""
    if not raw_lower:
        return ""
    # Prefer longer tokens so "new york" wins over "york" if both existed.
    for token, code in sorted(LOCATION_COUNTRY_HINTS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if token in raw_lower:
            c = (code or "").strip().upper()
            if len(c) == 2 and c.isalpha():
                return c
    return ""


def _country_from_norm_keys(raw_lower: str) -> str:
    """Last-resort: token appears as a key in COUNTRY_NORM (substring)."""
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
    # Single unbroken alpha token (typical bot noise).
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
