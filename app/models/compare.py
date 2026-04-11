"""Compare scoring engine for side-by-side job comparison.

Pure Python, deterministic scoring. No database writes.
Weights are documented and overridable.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional


DEFAULT_WEIGHTS: Dict[str, int] = {
    "salary_present": 25,
    "salary_confidence": 20,
    "freshness": 20,
    "remote": 15,
    "description_quality": 20,
}


def _parse_date(raw) -> Optional[datetime]:
    """Best-effort parse of a date value to a datetime."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:len(fmt)], fmt)
        except (ValueError, IndexError):
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def score_job(job_dict: Dict, weights: Optional[Dict[str, int]] = None) -> Dict:
    """Score a single job dict against quality heuristics.

    Returns {"total": int, "breakdown": {factor: int, ...}}.
    Each breakdown value is either 0 or the weight value (binary pass/fail).
    """
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    breakdown: Dict[str, int] = {}

    salary_text = str(job_dict.get("job_salary_range") or job_dict.get("salary") or "").strip()
    breakdown["salary_present"] = w["salary_present"] if salary_text else 0

    has_estimate = bool(job_dict.get("salary_min") or job_dict.get("estimated_salary"))
    breakdown["salary_confidence"] = w["salary_confidence"] if has_estimate else 0

    date_val = job_dict.get("date") or job_dict.get("date_posted")
    dt = _parse_date(date_val)
    if dt is not None:
        now = datetime.now(timezone.utc)
        dt_aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        days_old = (now - dt_aware).days
        breakdown["freshness"] = w["freshness"] if days_old <= 14 else 0
    else:
        breakdown["freshness"] = 0

    location = str(job_dict.get("location") or "").lower()
    breakdown["remote"] = w["remote"] if "remote" in location else 0

    desc = str(job_dict.get("job_description") or job_dict.get("description") or "")
    breakdown["description_quality"] = w["description_quality"] if len(desc) > 200 else 0

    total = sum(breakdown.values())
    return {"total": total, "breakdown": breakdown}


def compare_jobs(job_dicts: List[Dict], weights: Optional[Dict[str, int]] = None) -> List[Dict]:
    """Score and rank multiple jobs, returning them sorted by total descending.

    Each dict in the returned list gets an added "_score" key with the score result.
    """
    scored = []
    for job in job_dicts:
        result = score_job(job, weights)
        enriched = dict(job)
        enriched["_score"] = result
        scored.append(enriched)
    scored.sort(key=lambda j: j["_score"]["total"], reverse=True)
    return scored
