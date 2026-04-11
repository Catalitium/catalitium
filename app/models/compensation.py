"""Compensation confidence scoring engine.

Transforms raw salary data from multiple sources into a CompensationDisplay
dict with a 0-100 confidence score, source provenance label, and display-ready
salary figures.  Pure Python, deterministic, no database access.

CompensationDisplay shape (from AGENT_CONTRACT.md):
    {
        "source": str,          # "employer" | "estimated" | "crowd" | "unavailable"
        "confidence": int,      # 0-100
        "median": float | None,
        "currency": str | None, # ISO 4217
        "range_low": int | None,
        "range_high": int | None,
        "methodology_url": str, # url_for("compensation_methodology")
    }
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


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
    """Score compensation data quality and return a CompensationDisplay dict.

    Parameters
    ----------
    job_row : dict
        A dict with at least: ``salary`` (text from employer), ``job_salary``
        (int from employer), ``salary_min`` / ``salary_max`` (ints, may be
        pre-computed), ``median_salary_currency``.
    salary_ref_result : tuple | None
        Result of ``get_salary_for_location``: ``(median_salary, currency)`` or
        None when no reference data exists.
    has_crowd_data : bool
        True when at least one ``salary_submissions`` row matched the job's
        title + location.
    ref_match_level : str
        Granularity of the salary reference match.  One of ``"city"``,
        ``"region"``, ``"country"``, ``"fallback"``, or ``"none"``.
    methodology_url : str
        Absolute or relative URL for the methodology page.

    Returns
    -------
    dict  (CompensationDisplay)
    """

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

    # --- Source determination (priority order) ---
    if has_employer:
        source = "employer"
    elif has_ref:
        source = "estimated"
    elif has_crowd_data:
        source = "crowd"
    # else: stays "unavailable"

    # --- Score: employer salary text present (+40) ---
    if has_employer:
        score += 40

    # --- Score: salary reference match level ---
    if has_ref:
        level_scores = {
            "city": 30,
            "region": 20,
            "country": 15,
            "fallback": 5,
            "none": 0,
        }
        score += level_scores.get(ref_match_level, 5)

    # --- Score: crowd-sourced data (+15) ---
    if has_crowd_data:
        score += 15

    # --- Score: location specificity bonus ---
    if ref_match_level == "city":
        score += 10
    elif ref_match_level == "region":
        score += 5

    # --- Populate salary figures ---
    if has_ref:
        median = float(salary_ref_result[0])
        currency = salary_ref_result[1] or currency

    # Prefer pre-computed range from the route (respects uplift logic)
    pre_low = job_row.get("salary_min")
    pre_high = job_row.get("salary_max")
    if pre_low is not None and pre_high is not None:
        range_low = int(pre_low)
        range_high = int(pre_high)

    # Currency fallback chain
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
    """Return a Tailwind-friendly color token for the confidence score.

    - >= 70  -> "green"
    - >= 40  -> "amber"
    - <  40  -> "gray"
    """
    if score >= 70:
        return "green"
    if score >= 40:
        return "amber"
    return "gray"


def source_label(source: str) -> str:
    """Human-readable label for the compensation source."""
    return {
        "employer": "Employer provided",
        "estimated": "Estimated from market data",
        "crowd": "Community reported",
        "unavailable": "Not available",
    }.get(source, "Not available")
