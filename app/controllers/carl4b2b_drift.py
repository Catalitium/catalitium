"""Salary Drift for CARL B2B catalog samples.

Computes the median salary delta between the newer half and older half of
the parseable-salary rows in a single analysis pass. Sample-adaptive so it
works on both stale and fresh catalog slices. No schema changes, no
network calls.

Gate:
- Requires at least ``min_samples`` rows with BOTH a parseable salary AND
  a parseable date. Below the gate, returns status="insufficient_data"
  with a visible note.

Direction thresholds:
- +5% or more .......... "Trending up"
- between -5% and +5% .. "Stable"
- -5% or less .......... "Trending down"
"""
from __future__ import annotations

from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from datetime import datetime

from ..models.money import parse_salary_range_string
from .carl4b2b_ghost import parse_posting_age_days

DEFAULT_MIN_SAMPLES = 10

_STABLE_THRESHOLD_PCT = 5.0
_MAX_REASONABLE_ANNUAL = 2_000_000


def _coerce_salary(value: Any) -> Optional[int]:
    if value is None:
        return None
    parsed = parse_salary_range_string(str(value))
    if parsed is None:
        return None
    if not (0 < parsed < _MAX_REASONABLE_ANNUAL):
        return None
    return int(round(parsed))


def _collect_pairs(
    rows: Iterable[Mapping[str, Any]],
    now: Optional[datetime],
) -> List[Tuple[int, int]]:
    pairs: List[Tuple[int, int]] = []
    for r in rows:
        salary = _coerce_salary(r.get("job_salary_range"))
        if salary is None:
            continue
        age = parse_posting_age_days(r.get("date"), now=now)
        if age is None:
            continue
        pairs.append((int(age), salary))
    return pairs


def _direction(delta_pct: float) -> Tuple[str, str]:
    if delta_pct >= _STABLE_THRESHOLD_PCT:
        return "up", "Trending up"
    if delta_pct <= -_STABLE_THRESHOLD_PCT:
        return "down", "Trending down"
    return "flat", "Stable"


def compute_salary_drift(
    rows: Iterable[Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> Dict[str, Any]:
    pairs = _collect_pairs(rows, now=now)
    sample_size = len(pairs)
    if sample_size < min_samples:
        return {
            "status": "insufficient_data",
            "sample_size": sample_size,
            "min_required": int(min_samples),
            "note": (
                f"Need at least {int(min_samples)} listings with parseable salary "
                f"and date; got {sample_size}."
            ),
        }

    # Sort newer-first (ascending age), then split halves. For an odd sample
    # size the middle row is included in the older half (conservative: keeps
    # the "newer" half as strictly newer).
    pairs.sort(key=lambda p: p[0])
    mid = sample_size // 2
    newer = pairs[:mid]
    older = pairs[mid:]

    newer_salaries = [s for _, s in newer]
    older_salaries = [s for _, s in older]
    newer_ages = [a for a, _ in newer]
    older_ages = [a for a, _ in older]

    new_med = int(round(median(newer_salaries)))
    old_med = int(round(median(older_salaries)))
    delta_abs = new_med - old_med
    delta_pct = round((delta_abs / old_med) * 100.0, 1) if old_med > 0 else 0.0

    direction, direction_label = _direction(delta_pct)

    return {
        "status": "ok",
        "sample_size": sample_size,
        "min_required": int(min_samples),
        "direction": direction,
        "direction_label": direction_label,
        "delta_abs": int(delta_abs),
        "delta_pct": delta_pct,
        "newer_half": {
            "count": len(newer),
            "median_salary": new_med,
            "age_min": int(min(newer_ages)) if newer_ages else 0,
            "age_max": int(max(newer_ages)) if newer_ages else 0,
        },
        "older_half": {
            "count": len(older),
            "median_salary": old_med,
            "age_min": int(min(older_ages)) if older_ages else 0,
            "age_max": int(max(older_ages)) if older_ages else 0,
        },
        "note": (
            f"Based on {sample_size} listings with parseable salary. "
            "Directional over catalog sample, not a forecast."
        ),
    }
