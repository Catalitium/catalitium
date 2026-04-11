"""Career decision intelligence: scoring, exposure, velocity, earnings, paths.

Read-only queries on existing jobs, salary, and salary_submissions tables.
No new tables or dependencies.
"""

import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .db import get_db, logger
from .jobs import Job
from .salary import get_salary_for_location, parse_salary_range_string

# ── AI keyword list used by compute_ai_exposure ──────────────────────────
_AI_KEYWORDS = [
    "artificial intelligence", "machine learning", "deep learning",
    "neural network", "llm", "gpt", "nlp", "computer vision",
    "generative ai", "ai agent", "automation", "copilot", "chatbot",
]
_AI_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in _AI_KEYWORDS), re.IGNORECASE
)

# ── Title progression maps ───────────────────────────────────────────────
_IC_LADDER = ["junior", "mid", "senior", "staff", "principal", "distinguished"]
_MGMT_LADDER = ["lead", "manager", "director", "vp", "head"]


def _level_index(title_lower: str) -> Tuple[int, str]:
    """Return (index, track) for a title on the IC or mgmt ladder."""
    for i, level in enumerate(_IC_LADDER):
        if level in title_lower:
            return i, "ic"
    for i, level in enumerate(_MGMT_LADDER):
        if level in title_lower:
            return i, "mgmt"
    return 1, "ic"  # default to mid-level IC


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════


def compute_worth_it_score(
    job_dict: Dict[str, Any],
    salary_ref: Optional[Tuple],
    company_stats: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Score a job 0-100 across five dimensions (each 0-20).

    Returns a WorthItScore dict with ``total`` and ``breakdown``.
    """
    breakdown: Dict[str, int] = {}

    # 1. salary_vs_market
    job_salary_str = job_dict.get("job_salary_range") or job_dict.get("salary") or ""
    job_salary_val = job_dict.get("job_salary") or parse_salary_range_string(str(job_salary_str))
    has_salary = job_salary_val is not None and job_salary_val
    median = float(salary_ref[0]) if salary_ref else None
    if has_salary and median:
        breakdown["salary_vs_market"] = 20 if float(job_salary_val) >= median else 10
    elif has_salary:
        breakdown["salary_vs_market"] = 10
    elif median:
        breakdown["salary_vs_market"] = 5
    else:
        breakdown["salary_vs_market"] = 0

    # 2. company_signal
    job_count = int(company_stats.get("job_count", 0)) if company_stats else 0
    latest_date_raw = (company_stats.get("latest_date") or "") if company_stats else ""
    recent_post = False
    if latest_date_raw:
        try:
            if isinstance(latest_date_raw, datetime):
                ld = latest_date_raw
            elif hasattr(latest_date_raw, "isoformat"):
                ld = datetime.fromisoformat(latest_date_raw.isoformat())
            else:
                ld = datetime.fromisoformat(str(latest_date_raw).replace("Z", "+00:00"))
            if ld.tzinfo is None:
                ld = ld.replace(tzinfo=timezone.utc)
            recent_post = (datetime.now(timezone.utc) - ld) <= timedelta(days=14)
        except Exception:
            pass
    if job_count >= 10 and recent_post:
        breakdown["company_signal"] = 20
    elif job_count >= 5:
        breakdown["company_signal"] = 10
    elif job_count >= 2:
        breakdown["company_signal"] = 5
    else:
        breakdown["company_signal"] = 0

    # 3. role_quality
    desc = job_dict.get("job_description") or job_dict.get("description") or ""
    location = job_dict.get("location") or ""
    rq = 0
    if len(desc) > 500:
        rq += 8
    elif len(desc) > 200:
        rq += 4
    if has_salary:
        rq += 6
    if location and location.lower() not in ("", "remote", "anywhere"):
        rq += 6
    breakdown["role_quality"] = min(rq, 20)

    # 4. remote_availability
    loc_lower = location.lower()
    if "remote" in loc_lower:
        breakdown["remote_availability"] = 20
    elif "hybrid" in loc_lower:
        breakdown["remote_availability"] = 10
    else:
        breakdown["remote_availability"] = 0

    # 5. alternatives_count — caller can supply or we default to 0
    alt_count = job_dict.get("_alternatives_count", 0)
    if alt_count >= 10:
        breakdown["alternatives_count"] = 20
    elif alt_count >= 5:
        breakdown["alternatives_count"] = 10
    elif alt_count >= 2:
        breakdown["alternatives_count"] = 5
    else:
        breakdown["alternatives_count"] = 0

    total = sum(breakdown.values())
    return {"total": min(total, 100), "breakdown": breakdown}


def find_alternatives(
    title: str,
    location: str,
    exclude_id: Optional[int] = None,
    limit: int = 5,
) -> List[Dict]:
    """Search for similar jobs by title, excluding *exclude_id*."""
    try:
        country = ""
        if location:
            parts = [p.strip() for p in location.split(",")]
            if parts:
                country = parts[-1]
        results = Job.search(title=title, country=country, limit=limit + 5)
        filtered = [
            r for r in results
            if r.get("id") != exclude_id
        ]
        return filtered[:limit]
    except Exception as exc:
        logger.debug("find_alternatives failed: %s", exc)
        return []


def compute_ai_exposure(function_category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Rank function categories by AI-keyword prevalence in job descriptions.

    Returns a list of AIExposure dicts sorted by exposure_pct desc.
    """
    try:
        db = get_db()
        with db.cursor() as cur:
            where = ""
            params: list = []
            if function_category:
                where = "WHERE LOWER(job_title_norm) LIKE %s ESCAPE '\\'"
                params.append(f"%{function_category.lower()}%")
            cur.execute(
                f"""
                SELECT
                    COALESCE(NULLIF(job_title_norm, ''), LOWER(job_title)) AS func,
                    job_description,
                    job_salary
                FROM jobs
                {where}
                """,
                params,
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.debug("compute_ai_exposure query failed: %s", exc)
        return []

    buckets: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        raw_title = (row[0] or "").strip().lower()
        desc = row[1] or ""
        salary_val = row[2]

        func_name = _categorize_function(raw_title)
        if func_name not in buckets:
            buckets[func_name] = {"total": 0, "ai": 0, "salaries": []}
        buckets[func_name]["total"] += 1
        if _AI_PATTERN.search(desc):
            buckets[func_name]["ai"] += 1
        if salary_val:
            buckets[func_name]["salaries"].append(float(salary_val))

    results = []
    for func_name, data in buckets.items():
        if data["total"] < 2:
            continue
        pct = (data["ai"] / data["total"]) * 100
        median_sal = None
        if data["salaries"]:
            sorted_s = sorted(data["salaries"])
            mid = len(sorted_s) // 2
            median_sal = sorted_s[mid] if len(sorted_s) % 2 else (sorted_s[mid - 1] + sorted_s[mid]) / 2
        cat = "ai-native" if pct > 50 else ("ai-adjacent" if pct >= 20 else "ai-distant")
        results.append({
            "function_name": func_name,
            "exposure_pct": round(pct, 1),
            "category": cat,
            "job_count": data["total"],
            "median_salary": median_sal,
        })
    results.sort(key=lambda x: -x["exposure_pct"])
    return results


def get_hiring_velocity(
    location: Optional[str] = None,
    function: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Compare per-company hiring in last 30 days vs previous 30 days."""
    try:
        db = get_db()
        with db.cursor() as cur:
            clauses = []
            params: list = []
            if location:
                clauses.append("LOWER(COALESCE(location,'')) LIKE %s ESCAPE '\\'")
                params.append(f"%{location.lower()}%")
            if function:
                clauses.append("LOWER(COALESCE(job_title_norm,'')) LIKE %s ESCAPE '\\'")
                params.append(f"%{function.lower()}%")
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            cur.execute(
                f"""
                SELECT
                    company_name,
                    COUNT(*) FILTER (WHERE date >= NOW() - INTERVAL '30 days') AS recent,
                    COUNT(*) FILTER (WHERE date >= NOW() - INTERVAL '60 days'
                                       AND date < NOW() - INTERVAL '30 days') AS previous,
                    COUNT(*) AS total
                FROM jobs
                {where}
                GROUP BY company_name
                HAVING COUNT(*) >= 2
                ORDER BY COUNT(*) FILTER (WHERE date >= NOW() - INTERVAL '30 days') DESC
                LIMIT %s
                """,
                params + [limit],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as exc:
        logger.debug("get_hiring_velocity query failed: %s", exc)
        return []

    results = []
    for row in rows:
        recent = int(row.get("recent") or 0)
        previous = int(row.get("previous") or 0)
        if previous > 0:
            velocity_pct = round(((recent - previous) / previous) * 100, 1)
        elif recent > 0:
            velocity_pct = 100.0
        else:
            velocity_pct = 0.0
        if velocity_pct > 20:
            trend = "growing"
        elif velocity_pct < -20:
            trend = "declining"
        else:
            trend = "stable"
        results.append({
            "company_name": row.get("company_name") or "",
            "recent_count": recent,
            "previous_count": previous,
            "velocity_pct": velocity_pct,
            "trend": trend,
            "total_jobs": int(row.get("total") or 0),
        })
    return results


def estimate_earnings(
    title: str,
    location: str,
    currency: str = "EUR",
) -> Dict[str, Any]:
    """Build a low/median/high salary estimate from reference + crowd submissions."""
    result: Dict[str, Any] = {
        "base_low": None,
        "base_median": None,
        "base_high": None,
        "currency": currency,
        "location": location,
        "title": title,
        "data_source": "insufficient",
    }

    ref_data = get_salary_for_location(location) if location else None
    ref_median = float(ref_data[0]) if ref_data else None
    ref_currency = ref_data[1] if ref_data else None

    sub_salaries: List[float] = []
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT base_salary FROM salary_submissions
                WHERE LOWER(job_title) LIKE %s ESCAPE '\\'
                  AND LOWER(location) LIKE %s ESCAPE '\\'
                """,
                (f"%{title.lower()}%", f"%{location.lower()}%"),
            )
            sub_salaries = [float(r[0]) for r in cur.fetchall() if r[0]]
    except Exception as exc:
        logger.debug("estimate_earnings submissions query failed: %s", exc)

    if ref_median and sub_salaries:
        all_points = sub_salaries + [ref_median]
        all_points.sort()
        n = len(all_points)
        median = all_points[n // 2]
        low = all_points[max(0, int(n * 0.25))]
        high = all_points[min(n - 1, int(n * 0.75))]
        result.update(
            base_low=int(low),
            base_median=int(median),
            base_high=int(high),
            currency=ref_currency or currency,
            data_source="combined",
        )
    elif ref_median:
        result.update(
            base_low=int(ref_median * 0.8),
            base_median=int(ref_median),
            base_high=int(ref_median * 1.2),
            currency=ref_currency or currency,
            data_source="reference",
        )
    elif sub_salaries:
        sub_salaries.sort()
        n = len(sub_salaries)
        median = sub_salaries[n // 2]
        low = sub_salaries[max(0, int(n * 0.25))]
        high = sub_salaries[min(n - 1, int(n * 0.75))]
        result.update(
            base_low=int(low),
            base_median=int(median),
            base_high=int(high),
            data_source="submissions",
        )

    return result


def get_career_paths(title_norm: str) -> Dict[str, Any]:
    """Derive progression, lateral moves, and top employers from jobs table."""
    title_lower = (title_norm or "").strip().lower()
    level_idx, track = _level_index(title_lower)

    base_function = re.sub(
        r"\b(junior|mid|senior|staff|principal|distinguished|lead|manager|director|vp|head)\b",
        "", title_lower,
    ).strip()
    base_function = re.sub(r"\s+", " ", base_function).strip()
    if not base_function:
        base_function = title_lower

    next_steps: List[Dict] = []
    lateral_moves: List[Dict] = []

    # IC next steps
    ic_next = _IC_LADDER[level_idx + 1:level_idx + 3] if level_idx + 1 < len(_IC_LADDER) else []
    for level in ic_next:
        search_term = f"{level} {base_function}"
        _add_path_node(search_term, next_steps)

    # Mgmt path if IC
    if track == "ic" and level_idx >= 2:
        for level in _MGMT_LADDER[:2]:
            search_term = f"{level} {base_function}"
            _add_path_node(search_term, next_steps)
    elif track == "mgmt":
        mgmt_next = _MGMT_LADDER[level_idx + 1:level_idx + 3] if level_idx + 1 < len(_MGMT_LADDER) else []
        for level in mgmt_next:
            search_term = f"{level} {base_function}"
            _add_path_node(search_term, next_steps)

    # Lateral moves: same level, different function
    lateral_functions = _get_lateral_functions(base_function)
    current_level = _IC_LADDER[level_idx] if track == "ic" and level_idx < len(_IC_LADDER) else (
        _MGMT_LADDER[level_idx] if track == "mgmt" and level_idx < len(_MGMT_LADDER) else ""
    )
    for func in lateral_functions[:4]:
        search_term = f"{current_level} {func}" if current_level else func
        _add_path_node(search_term, lateral_moves)

    # Top employers
    companies_hiring = _get_top_employers(title_lower)

    return {
        "current": title_norm,
        "next_steps": next_steps,
        "lateral_moves": lateral_moves,
        "companies_hiring": companies_hiring,
    }


def compute_market_position(
    title: str,
    location: str,
    years_exp: int,
    current_salary: float,
    currency: str = "EUR",
) -> Dict[str, Any]:
    """Return a SalaryPercentile-like dict for the user's position in the market."""
    ref_data = get_salary_for_location(location) if location else None
    ref_median = float(ref_data[0]) if ref_data else None

    all_salaries: List[float] = []
    if ref_median:
        all_salaries.append(ref_median)

    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT base_salary FROM salary_submissions
                WHERE LOWER(job_title) LIKE %s ESCAPE '\\'
                  AND LOWER(location) LIKE %s ESCAPE '\\'
                """,
                (f"%{title.lower()}%", f"%{location.lower()}%"),
            )
            for r in cur.fetchall():
                if r[0]:
                    all_salaries.append(float(r[0]))
    except Exception as exc:
        logger.debug("compute_market_position query failed: %s", exc)

    if not all_salaries:
        median = None
        percentile_rank = 50
        label = "insufficient_data"
    else:
        all_salaries.sort()
        n = len(all_salaries)
        median = all_salaries[n // 2]
        below = sum(1 for s in all_salaries if s < current_salary)
        percentile_rank = min(99, max(1, int((below / n) * 100)))
        if percentile_rank >= 65:
            label = "above_market"
        elif percentile_rank >= 35:
            label = "at_market"
        else:
            label = "below_market"

    # Adjust for experience: each year beyond 3 bumps percentile slightly
    exp_adjustment = max(0, (years_exp - 3)) * 1.5
    percentile_rank = min(99, int(percentile_rank + exp_adjustment))

    return {
        "title": title,
        "location": location,
        "user_salary": current_salary,
        "currency": currency,
        "median": median,
        "percentile_rank": percentile_rank,
        "label": label,
    }


# ═══════════════════════════════════════════════════════════════════════════
# PRIVATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _categorize_function(title_lower: str) -> str:
    """Map a normalised job title to a broad function category."""
    categories = [
        ("AI & Machine Learning", ["machine learning", "ml ", "ai ", "artificial intelligence", "deep learning", "nlp", "computer vision"]),
        ("Data & Analytics", ["data", "analyst", "analytics", "business intelligence", "bi "]),
        ("Security", ["security", "infosec", "cybersecurity", "penetration"]),
        ("QA & Testing", ["qa ", "quality", "test ", "testing"]),
        ("Product", ["product manager", "product owner", "product lead"]),
        ("Design", ["design", "ux", "ui ", "creative"]),
        ("Engineering", ["engineer", "developer", "programmer", "devops", "sre", "backend", "frontend", "fullstack", "full-stack", "software"]),
        ("Marketing", ["marketing", "growth", "seo", "content"]),
        ("Sales", ["sales", "account executive", "business development", "bdr", "sdr"]),
        ("Operations", ["operations", "ops ", "logistics", "supply chain"]),
        ("Management", ["manager", "director", "vp ", "head of", "chief"]),
        ("Support", ["support", "customer success", "helpdesk"]),
    ]
    for cat_name, keywords in categories:
        for kw in keywords:
            if kw in title_lower:
                return cat_name
    return "Other"


def _get_lateral_functions(base_function: str) -> List[str]:
    """Return a few lateral-move function names for a given base function."""
    laterals_map = {
        "engineer": ["data engineer", "devops engineer", "security engineer", "ml engineer"],
        "developer": ["data engineer", "devops engineer", "solutions architect"],
        "data": ["software engineer", "ml engineer", "product analyst"],
        "product": ["project manager", "program manager", "business analyst"],
        "design": ["product manager", "frontend developer", "ux researcher"],
        "marketing": ["product marketing", "growth analyst", "content strategist"],
        "analyst": ["data engineer", "product analyst", "business intelligence"],
    }
    for key, moves in laterals_map.items():
        if key in base_function:
            return moves
    return ["software engineer", "data analyst", "product manager"]


def _add_path_node(search_term: str, target_list: List[Dict]) -> None:
    """Query jobs for *search_term* and append a summary node to *target_list*."""
    try:
        results = Job.search(title=search_term, limit=50)
        if not results:
            return
        salaries = []
        for r in results:
            sal = r.get("job_salary") or parse_salary_range_string(r.get("job_salary_range") or "")
            if sal:
                salaries.append(float(sal))
        median_sal = None
        if salaries:
            salaries.sort()
            mid = len(salaries) // 2
            median_sal = salaries[mid]
        target_list.append({
            "title": search_term.title(),
            "median_salary": median_sal,
            "job_count": len(results),
        })
    except Exception as exc:
        logger.debug("_add_path_node(%s) failed: %s", search_term, exc)


def _get_top_employers(title_lower: str) -> List[Dict]:
    """Return companies with the most jobs matching *title_lower*."""
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT company_name, COUNT(*) AS cnt
                FROM jobs
                WHERE LOWER(COALESCE(job_title_norm, '')) LIKE %s ESCAPE '\\'
                GROUP BY company_name
                HAVING COUNT(*) >= 2
                ORDER BY cnt DESC
                LIMIT 10
                """,
                (f"%{title_lower}%",),
            )
            return [{"name": r[0], "count": r[1]} for r in cur.fetchall() if r[0]]
    except Exception as exc:
        logger.debug("_get_top_employers failed: %s", exc)
        return []
