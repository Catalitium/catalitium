"""Salary data access and parsing utilities.

All SQL for the salary and salary_submissions tables lives here.
Pure parsing helpers (no DB) are also here since they belong to the salary domain.
"""

import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from .db import get_db, logger


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def insert_salary_submission(
    *,
    job_title: str,
    company: str = "",
    location: str,
    seniority: str,
    base_salary: int,
    currency: str,
    years_exp: Optional[int] = None,
    email: Optional[str] = None,
) -> str:
    """Insert a crowd-sourced salary data point; return 'ok' or 'error'."""
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO salary_submissions(
                    job_title, company, location, seniority,
                    base_salary, currency, years_exp, email, created_at
                )
                VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    (job_title or "").strip(),
                    (company or "").strip() or None,
                    (location or "").strip(),
                    (seniority or "").strip(),
                    int(base_salary),
                    (currency or "CHF").strip().upper(),
                    years_exp,
                    (email or "").strip() or None,
                    _now_iso(),
                ),
            )
        return "ok"
    except Exception as exc:
        logger.warning("insert_salary_submission failed: %s", exc, exc_info=True)
        return "error"


def get_salary_for_location(location: str):
    """Best-effort: return (median_salary, currency) for a location string.

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
    median_col = "median_salary"
    currency_col = "currency"
    pieces = [p.strip() for p in re.split(r"[,;/\\-]|\\(|\\)", loc) if p and p.strip()]
    candidates: List[str] = []
    if pieces:
        candidates.extend(pieces)
    candidates.append(loc)

    try:
        with db.cursor() as cur:
            lower_cands = [c.lower() for c in candidates if c]
            if lower_cands:
                cur.execute(
                    f"""
                    SELECT {median_col}, {currency_col}, 1 AS priority FROM salary
                      WHERE LOWER(city) = ANY(%s) AND {median_col} IS NOT NULL
                    UNION ALL
                    SELECT {median_col}, {currency_col}, 2 FROM salary
                      WHERE LOWER(region) = ANY(%s) AND {median_col} IS NOT NULL
                    UNION ALL
                    SELECT {median_col}, {currency_col}, 3 FROM salary
                      WHERE LOWER(country) = ANY(%s) AND {median_col} IS NOT NULL
                    ORDER BY 3
                    LIMIT 1
                    """,
                    (lower_cands, lower_cands, lower_cands),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    return float(row[0]), (row[1] or None)

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
    except Exception as exc:
        logger.warning("get_salary_for_location(%r) failed: %s", loc, exc)
        return None
    return None


def parse_money_numbers(text: str) -> List[int]:
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

    return s, None, None


def _compact_salary_number(n: float) -> str:
    """Return a compact string like '110k' or '1.2M' for a numeric salary."""
    if n is None:
        return ""
    try:
        v = float(n)
    except Exception:
        return str(n)
    if v < 1000:
        return str(int(round(v)))
    k = int(round(v / 1000.0))
    if k < 1000:
        k_rounded = int(round(k / 10.0) * 10)
        if k_rounded <= 0:
            k_rounded = max(1, k)
        return f"{k_rounded}k"
    m = v / 1_000_000.0
    m_rounded = round(m, 1)
    if m_rounded.is_integer():
        return f"{int(m_rounded)}M"
    return f"{m_rounded}M"


def salary_range_around(median: float, pct: float = 0.2):
    """Return (low, high, low_str, high_str) range around median using pct (default 20%)."""
    if median is None:
        return None
    try:
        m = float(median)
    except Exception:
        return None
    low = m * (1.0 - pct)
    high = m * (1.0 + pct)

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


def parse_salary_range_string(s: str) -> Optional[float]:
    """Parse a salary range string and return the midpoint as a float.

    Handles formats like:
    - "110k-120k" or "110k–120k" (en dash)
    - "$110,000 - $120,000"
    - "120000" or "120k" (single value)
    - "CHF 120k-150k" or "USD 100k-120k" (with currency prefix)

    Returns None if unparseable.
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None

    s_clean = re.sub(r'^(USD|CHF|EUR|GBP|USD\$|\$)\s*', '', s, flags=re.IGNORECASE)

    range_match = re.search(r'(\d[\d,.\s]*k?)\s*[-–—]\s*(\d[\d,.\s]*k?)', s_clean)
    if range_match:
        low_vals = parse_money_numbers(range_match.group(1))
        high_vals = parse_money_numbers(range_match.group(2))
        if low_vals and high_vals:
            return float((low_vals[0] + high_vals[-1]) / 2.0)
        elif low_vals:
            return float(low_vals[0])
        elif high_vals:
            return float(high_vals[-1])

    single_vals = parse_money_numbers(s_clean)
    if single_vals:
        return float(single_vals[0])

    return None
