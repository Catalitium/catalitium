"""Salary tables, parsing, compensation scoring, and salary analytics (merged domain module)."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .db import get_db, logger


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
                    now_iso(),
                ),
            )
        return "ok"
    except Exception as exc:
        logger.warning("insert_salary_submission failed: %s", exc, exc_info=True)
        return "error"


def get_salary_for_location(location: str):
    """Best-effort: return (median_salary, currency) for a location string."""
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
        logger.debug("get_salary_for_location(%r) failed: %s", loc, exc)
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
        return cleaned, None, vals[0] if vals else None, None

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
    """Parse a salary range string and return the midpoint as a float."""
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


# --- Compensation (from compensation.py) ---


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))


def compute_compensation_confidence(
    job_row: Dict[str, Any],
    salary_ref_result: Optional[Tuple[float, Optional[str]]] = None,
    *,
    has_crowd_data: bool = False,
    ref_match_level: str = "none",
    methodology_url: str = "/compensation/methodology",
) -> Dict[str, Any]:
    score = 0
    source = "unavailable"
    median: Optional[float] = None
    currency: Optional[str] = None
    range_low: Optional[int] = None
    range_high: Optional[int] = None

    employer_salary_text = (job_row.get("salary") or "").strip()
    employer_salary_int = job_row.get("job_salary")
    has_employer = bool(employer_salary_text) or (
        employer_salary_int is not None and employer_salary_int > 0
    )

    has_ref = salary_ref_result is not None and salary_ref_result[0] is not None

    if has_employer:
        source = "employer"
    elif has_ref:
        source = "estimated"
    elif has_crowd_data:
        source = "crowd"

    if has_employer:
        score += 40

    if has_ref:
        level_scores = {
            "city": 30,
            "region": 20,
            "country": 15,
            "fallback": 5,
            "none": 0,
        }
        score += level_scores.get(ref_match_level, 5)

    if has_crowd_data:
        score += 15

    if ref_match_level == "city":
        score += 10
    elif ref_match_level == "region":
        score += 5

    if has_ref:
        median = float(salary_ref_result[0])
        currency = salary_ref_result[1] or currency

    pre_low = job_row.get("salary_min")
    pre_high = job_row.get("salary_max")
    if pre_low is not None and pre_high is not None:
        range_low = int(pre_low)
        range_high = int(pre_high)

    if currency is None:
        currency = job_row.get("median_salary_currency") or None

    score = _clamp(score)

    return {
        "source": source,
        "confidence": score,
        "median": median,
        "currency": currency,
        "range_low": range_low,
        "range_high": range_high,
        "methodology_url": methodology_url,
    }


def confidence_color(score: int) -> str:
    if score >= 70:
        return "green"
    if score >= 40:
        return "amber"
    return "gray"


def source_label(source: str) -> str:
    return {
        "employer": "Employer provided",
        "estimated": "Estimated from market data",
        "crowd": "Community reported",
        "unavailable": "Not available",
    }.get(source, "Not available")


# --- Salary analytics (from salary_analytics.py) ---

_CACHE_TTL = 300
_CACHE_MAX = 64
_cache: Dict[tuple, tuple] = {}


def _cache_get(key: tuple):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    return None


def _cache_set(key: tuple, value):
    _cache[key] = (time.time(), value)
    if len(_cache) > _CACHE_MAX:
        oldest = sorted(_cache.items(), key=lambda kv: kv[1][0])[: len(_cache) - _CACHE_MAX]
        for k, _ in oldest:
            _cache.pop(k, None)


_PPP_INDICES: Dict[str, float] = {
    "Zurich": 1.0,
    "San Francisco": 0.95,
    "New York": 0.90,
    "London": 0.75,
    "Berlin": 0.65,
    "Amsterdam": 0.72,
    "Paris": 0.70,
    "Dublin": 0.73,
    "Barcelona": 0.55,
    "Lisbon": 0.48,
    "Warsaw": 0.40,
    "Prague": 0.42,
    "Vienna": 0.68,
    "Munich": 0.70,
    "Stockholm": 0.72,
    "Copenhagen": 0.75,
    "Helsinki": 0.68,
    "Oslo": 0.80,
    "Singapore": 0.70,
    "Tokyo": 0.65,
    "Sydney": 0.72,
    "Toronto": 0.68,
    "Vancouver": 0.65,
    "Austin": 0.82,
    "Seattle": 0.88,
    "Boston": 0.87,
    "Chicago": 0.80,
    "Denver": 0.82,
    "Miami": 0.78,
    "Bangalore": 0.25,
    "Remote": 0.75,
}


def get_ppp_indices() -> Dict[str, float]:
    return dict(_PPP_INDICES)


def compute_percentile(
    title: str,
    location: str,
    user_salary: float,
    currency: str = "CHF",
) -> dict:
    median: Optional[float] = None
    try:
        result = get_salary_for_location(location)
        if result:
            median = float(result[0])
    except Exception as exc:
        logger.debug("compute_percentile salary lookup failed: %s", exc)

    if median and median > 0:
        raw = user_salary / median * 50.0
        percentile_rank = max(0, min(100, int(round(raw))))
    else:
        percentile_rank = 50

    if percentile_rank > 60:
        label = "above_market"
    elif percentile_rank < 40:
        label = "below_market"
    else:
        label = "at_market"

    return {
        "title": title,
        "location": location,
        "user_salary": float(user_salary),
        "currency": currency,
        "median": median,
        "percentile_rank": percentile_rank,
        "label": label,
    }


def compare_cities_salary(title: str, cities: List[str]) -> List[dict]:
    ppp = get_ppp_indices()
    results: List[dict] = []
    for city in cities:
        raw_median: Optional[float] = None
        currency: Optional[str] = None
        try:
            sal = get_salary_for_location(city)
            if sal:
                raw_median = float(sal[0])
                currency = sal[1]
        except Exception as exc:
            logger.debug("compare_cities_salary lookup for %r failed: %s", city, exc)

        ppp_index = ppp.get(city, 0.75)
        adjusted = round(raw_median / ppp_index) if raw_median and ppp_index else None

        results.append({
            "city": city,
            "raw_median": raw_median,
            "currency": currency,
            "ppp_index": ppp_index,
            "adjusted_salary": adjusted,
        })
    return results


def get_function_benchmarks(location: Optional[str] = None) -> List[dict]:
    from .catalog import categorize_function

    cache_key = ("fn_benchmarks", (location or "").lower())
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    benchmarks: Dict[str, List[int]] = {}
    try:
        db = get_db()
        with db.cursor() as cur:
            if location:
                cur.execute(
                    """SELECT job_title_norm, job_salary
                       FROM jobs
                       WHERE job_salary IS NOT NULL
                         AND job_salary > 0
                         AND LOWER(location) LIKE %s
                       LIMIT 5000""",
                    (f"%{location.lower()}%",),
                )
            else:
                cur.execute(
                    """SELECT job_title_norm, job_salary
                       FROM jobs
                       WHERE job_salary IS NOT NULL AND job_salary > 0
                       LIMIT 5000""",
                )
            for row in cur.fetchall():
                title_norm = row[0] or ""
                salary_val = row[1]
                cat = categorize_function(title_norm)
                benchmarks.setdefault(cat, []).append(int(salary_val))
    except Exception as exc:
        logger.debug("get_function_benchmarks failed: %s", exc)

    results: List[dict] = []
    for fn, salaries in sorted(benchmarks.items()):
        if not salaries:
            continue
        salaries.sort()
        mid = len(salaries) // 2
        median = salaries[mid] if len(salaries) % 2 else (salaries[mid - 1] + salaries[mid]) // 2
        results.append({
            "function": fn,
            "median_salary": median,
            "job_count": len(salaries),
            "currency": "CHF",
        })
    results.sort(key=lambda x: x["median_salary"], reverse=True)
    _cache_set(cache_key, results)
    return results


def get_salary_trends(
    title_category: Optional[str] = None,
    city: Optional[str] = None,
    months: int = 12,
) -> List[dict]:
    from .catalog import categorize_function

    cache_key = ("sal_trends", (title_category or "").lower(), (city or "").lower(), months)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    trends: List[dict] = []
    try:
        db = get_db()
        with db.cursor() as cur:
            conditions = ["job_salary IS NOT NULL", "job_salary > 0"]
            params: list = []

            if city:
                conditions.append("LOWER(location) LIKE %s")
                params.append(f"%{city.lower()}%")

            where = " AND ".join(conditions)
            cur.execute(
                f"""SELECT
                        TO_CHAR(date, 'YYYY-MM') AS month,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY job_salary) AS median_sal,
                        COUNT(*) AS cnt
                    FROM jobs
                    WHERE {where}
                      AND date >= NOW() - INTERVAL '{int(months)} months'
                    GROUP BY TO_CHAR(date, 'YYYY-MM')
                    ORDER BY month DESC
                    LIMIT {int(months)}""",
                params,
            )
            for row in cur.fetchall():
                trends.append({
                    "month": row[0],
                    "median_salary": int(row[1]) if row[1] else 0,
                    "job_count": row[2],
                })
    except Exception as exc:
        logger.debug("get_salary_trends failed: %s", exc)

    if title_category and title_category != "All":
        try:
            db = get_db()
            with db.cursor() as cur:
                conditions = ["job_salary IS NOT NULL", "job_salary > 0"]
                params2: list = []
                if city:
                    conditions.append("LOWER(location) LIKE %s")
                    params2.append(f"%{city.lower()}%")
                where2 = " AND ".join(conditions)
                cur.execute(
                    f"""SELECT
                            TO_CHAR(date, 'YYYY-MM') AS month,
                            job_title_norm,
                            job_salary
                        FROM jobs
                        WHERE {where2}
                          AND date >= NOW() - INTERVAL '{int(months)} months'
                        LIMIT 10000""",
                    params2,
                )
                month_buckets: Dict[str, List[int]] = {}
                for row in cur.fetchall():
                    cat = categorize_function(row[1] or "")
                    if cat == title_category:
                        month_buckets.setdefault(row[0], []).append(int(row[2]))
                trends = []
                for m in sorted(month_buckets.keys(), reverse=True):
                    sals = sorted(month_buckets[m])
                    mid = len(sals) // 2
                    med = sals[mid] if len(sals) % 2 else (sals[mid - 1] + sals[mid]) // 2
                    trends.append({
                        "month": m,
                        "median_salary": med,
                        "job_count": len(sals),
                    })
        except Exception as exc:
            logger.debug("get_salary_trends category filter failed: %s", exc)

    _cache_set(cache_key, trends)
    return trends


def now_iso() -> str:
    """UTC timestamp in ISO-8601 seconds precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_salary_context(location: str) -> Dict[str, Any]:
    """Wrap ``get_salary_for_location`` with standardized None handling.

    Returns a dict with keys: ``median``, ``currency``, ``raw`` (the
    original tuple or None).  Callers never need to unpack/guard against
    None themselves.
    """
    result: Optional[Tuple[float, Optional[str]]] = None
    try:
        if location:
            result = get_salary_for_location(location)
    except Exception as exc:
        logger.debug("safe_salary_context(%r) lookup failed: %s", location, exc)

    if result and result[0] is not None:
        return {
            "median": float(result[0]),
            "currency": result[1] or None,
            "raw": result,
        }
    return {
        "median": None,
        "currency": None,
        "raw": None,
    }
