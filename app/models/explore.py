"""Explore module: quality scoring, function categorization, and discovery aggregations.

All queries are read-only against the existing ``jobs`` table.
No new tables or dependencies required.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .db import get_db, logger
from .taxonomy import FUNCTION_CATEGORIES, categorize_function  # single source of truth

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
# Quality score
# ---------------------------------------------------------------------------

def compute_quality_score(job_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Return a QualityScore dict (see AGENT_CONTRACT.md).

    Scoring breakdown (max 100):
      - has salary text         → +25
      - description > 200 chars → +25
      - specific location (city) → +20
      - posted within 30 days   → +15
      - company name present    → +15
    """
    breakdown: Dict[str, int] = {
        "salary": 0,
        "description": 0,
        "location": 0,
        "freshness": 0,
        "company": 0,
    }

    salary_text = job_dict.get("salary") or job_dict.get("job_salary_range") or ""
    if isinstance(salary_text, str) and salary_text.strip():
        breakdown["salary"] = 25
    elif isinstance(salary_text, (int, float)) and salary_text > 0:
        breakdown["salary"] = 25

    desc = job_dict.get("job_description") or job_dict.get("description") or ""
    if len(str(desc)) > 200:
        breakdown["description"] = 25

    city = job_dict.get("city") or ""
    if isinstance(city, str) and city.strip():
        breakdown["location"] = 20

    date_val = job_dict.get("date") or job_dict.get("date_raw") or ""
    if date_val:
        try:
            if hasattr(date_val, "date"):
                dt = date_val
            else:
                cleaned = str(date_val).strip()
                if re.match(r"^\d{8}$", cleaned):
                    cleaned = f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
                dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if hasattr(dt, "tzinfo") and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if (now - dt).days <= 30:
                breakdown["freshness"] = 15
        except (ValueError, TypeError, OverflowError):
            pass

    company = job_dict.get("company_name") or job_dict.get("company") or ""
    if isinstance(company, str) and company.strip():
        breakdown["company"] = 15

    total = min(100, max(0, sum(breakdown.values())))
    return {"total": total, "breakdown": breakdown}


# ---------------------------------------------------------------------------
# Hiring urgency
# ---------------------------------------------------------------------------

def get_hiring_urgency(company_name: str) -> bool:
    """True if company has 5+ jobs posted in the last 14 days."""
    if not company_name:
        return False
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FROM jobs
                   WHERE company_name = %s
                     AND date >= CURRENT_DATE - INTERVAL '14 days'""",
                [company_name],
            )
            row = cur.fetchone()
            return (row[0] if row else 0) >= 5
    except Exception as exc:
        logger.debug("get_hiring_urgency(%s) error: %s", company_name, exc)
        return False


# ---------------------------------------------------------------------------
# Explore Hub aggregations
# ---------------------------------------------------------------------------

def get_explore_data() -> Dict[str, Any]:
    """Return top titles, locations, and companies for the Explore Hub."""
    cache_key = ("explore_data",)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    result: Dict[str, Any] = {
        "top_titles": [],
        "top_locations": [],
        "top_companies": [],
    }
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(NULLIF(job_title_norm, ''), LOWER(job_title)) AS title_key,
                       COUNT(*) AS cnt,
                       MIN(CASE WHEN salary IS NOT NULL AND salary != '' THEN salary END) AS sample_salary
                FROM jobs
                GROUP BY title_key
                ORDER BY cnt DESC
                LIMIT 20
            """)
            cols = [d[0] for d in cur.description]
            result["top_titles"] = [
                {"name": r[0], "job_count": r[1], "salary_sample": r[2]}
                for r in cur.fetchall()
            ]

            cur.execute("""
                SELECT COALESCE(NULLIF(country, ''), 'Unknown') AS loc,
                       COUNT(*) AS cnt,
                       MIN(CASE WHEN salary IS NOT NULL AND salary != '' THEN salary END) AS sample_salary
                FROM jobs
                GROUP BY loc
                ORDER BY cnt DESC
                LIMIT 20
            """)
            result["top_locations"] = [
                {"name": r[0], "job_count": r[1], "salary_sample": r[2]}
                for r in cur.fetchall()
            ]

            cur.execute("""
                SELECT company_name,
                       COUNT(*) AS cnt,
                       MIN(CASE WHEN salary IS NOT NULL AND salary != '' THEN salary END) AS sample_salary
                FROM jobs
                WHERE company_name IS NOT NULL AND company_name != ''
                GROUP BY company_name
                ORDER BY cnt DESC
                LIMIT 20
            """)
            result["top_companies"] = [
                {"name": r[0], "job_count": r[1], "salary_sample": r[2]}
                for r in cur.fetchall()
            ]
    except Exception as exc:
        logger.warning("get_explore_data failed: %s", exc)

    _cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Remote-friendliness ranking
# ---------------------------------------------------------------------------

def get_remote_companies(limit: int = 50) -> List[Dict[str, Any]]:
    """Return companies ranked by % of remote job postings."""
    cache_key = ("remote_companies", limit)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("""
                SELECT company_name,
                       COUNT(*) AS total_jobs,
                       COUNT(CASE WHEN LOWER(COALESCE(location, '')) LIKE '%%remote%%' THEN 1 END) AS remote_jobs,
                       MAX(date) AS latest_date
                FROM jobs
                WHERE company_name IS NOT NULL AND company_name != ''
                GROUP BY company_name
                HAVING COUNT(*) >= 2
                   AND COUNT(CASE WHEN LOWER(COALESCE(location, '')) LIKE '%%remote%%' THEN 1 END) > 0
                ORDER BY COUNT(CASE WHEN LOWER(COALESCE(location, '')) LIKE '%%remote%%' THEN 1 END)::float
                         / COUNT(*)::float DESC,
                         COUNT(*) DESC
                LIMIT %s
            """, [int(limit)])
            rows = []
            for r in cur.fetchall():
                total = r[1] or 1
                remote = r[2] or 0
                rows.append({
                    "company_name": r[0],
                    "total_jobs": total,
                    "remote_jobs": remote,
                    "remote_pct": round(remote / total * 100, 1),
                    "latest_date": str(r[3]) if r[3] else "",
                })
            _cache_set(cache_key, rows)
            return rows
    except Exception as exc:
        logger.warning("get_remote_companies failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Function distribution
# ---------------------------------------------------------------------------

def get_function_distribution(location: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return job counts per function category with % having salary data."""
    cache_key = ("fn_distribution", (location or "").lower())
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        db = get_db()
        params: list = []
        where = ""
        if location:
            where = "WHERE LOWER(COALESCE(country, '')) = %s"
            params.append(location.strip().lower())
        with db.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(NULLIF(job_title_norm, ''), LOWER(job_title)) AS title_key,
                       salary
                FROM jobs {where}
            """, params)
            from collections import Counter
            cat_counts: Counter[str] = Counter()
            cat_salary: Counter[str] = Counter()
            for row in cur.fetchall():
                cat = categorize_function(row[0])
                cat_counts[cat] += 1
                if row[1] and str(row[1]).strip():
                    cat_salary[cat] += 1
            result = []
            for cat in sorted(cat_counts, key=cat_counts.get, reverse=True):  # type: ignore[arg-type]
                total = cat_counts[cat]
                with_sal = cat_salary.get(cat, 0)
                result.append({
                    "function": cat,
                    "job_count": total,
                    "has_salary_pct": round(with_sal / total * 100, 1) if total else 0,
                })
            _cache_set(cache_key, result)
            return result
    except Exception as exc:
        logger.warning("get_function_distribution failed: %s", exc)
        return []
