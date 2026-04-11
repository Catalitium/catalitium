"""Salary analytics: percentile calculator, PPP comparison, function benchmarks, trends.

Read-only queries on existing tables (jobs, salary, salary_submissions).
No new tables or dependencies.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from .db import get_db, logger
from .salary import get_salary_for_location
from .taxonomy import categorize_function  # single source of truth


# ---------------------------------------------------------------------------
# In-memory LRU cache (same pattern as jobs.py)
# ---------------------------------------------------------------------------

_CACHE_TTL = 300  # 5 minutes for expensive aggregation queries
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


# ---------------------------------------------------------------------------
# PPP cost-of-living indices (Zurich = 1.0 baseline)
# ---------------------------------------------------------------------------

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
    """Return the PPP index dictionary (city -> index, Zurich = 1.0)."""
    return dict(_PPP_INDICES)


# ---------------------------------------------------------------------------
# Percentile calculator (SalaryPercentile shape from AGENT_CONTRACT)
# ---------------------------------------------------------------------------

def compute_percentile(
    title: str,
    location: str,
    user_salary: float,
    currency: str = "CHF",
) -> dict:
    """Compute where *user_salary* sits relative to the market median.

    Returns the SalaryPercentile dict defined in AGENT_CONTRACT.md.
    percentile_rank = (user_salary / median * 50) clamped 0-100.
    """
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


# ---------------------------------------------------------------------------
# Cross-city salary comparison with PPP adjustment
# ---------------------------------------------------------------------------

def compare_cities_salary(title: str, cities: List[str]) -> List[dict]:
    """For each city return raw median + PPP-adjusted salary."""
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


# ---------------------------------------------------------------------------
# Function benchmarks (aggregate jobs.job_salary by category)
# ---------------------------------------------------------------------------

def get_function_benchmarks(location: Optional[str] = None) -> List[dict]:
    """Aggregate median job_salary grouped by function category.

    Uses a single query, then buckets in Python to avoid dynamic SQL.
    """
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


# ---------------------------------------------------------------------------
# Salary trends (monthly aggregation)
# ---------------------------------------------------------------------------

def get_salary_trends(
    title_category: Optional[str] = None,
    city: Optional[str] = None,
    months: int = 12,
) -> List[dict]:
    """Monthly median salary + job count from jobs table."""
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
