"""Ghost Likelihood Score for CARL B2B listings.

Pure, rule-based, dependency-light. Attaches a 0-100 score plus a factor
breakdown to each job row returned by Job.search. No schema changes, no
network calls, no LLM.

Signals (3 real + 1 placeholder):
  1. Posting age       0-40 pts   (from row.date)
  2. Repost frequency  0-20 pts   (same company + title_norm in sample)
  3. Salary signal     0-15 pts   (reuses app.models.money parser)
  4. Velocity mismatch 0  pts     (placeholder - needs jobs.last_seen_at)
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from ..models.money import parse_salary_range_string

_MAX_RAW_POINTS = 75

_AGE_BAND_FRESH = 14
_AGE_BAND_MILD = 30
_AGE_BAND_STALE = 60

_LABEL_ACTIVE = "Active"
_LABEL_UNCERTAIN = "Uncertain"
_LABEL_LOW = "Low hiring signal"


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[: len(fmt)], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_posting_age_days(value: Any, now: Optional[datetime] = None) -> Optional[int]:
    posted = _to_date(value)
    if posted is None:
        return None
    today = (now or datetime.now(timezone.utc)).date()
    return max(0, (today - posted).days)


def _repost_key(row: Mapping[str, Any]) -> Tuple[str, str]:
    company = str(row.get("company_name") or "").strip().lower()
    title = str(row.get("job_title_norm") or row.get("job_title") or "").strip().lower()
    return company, title


def compute_repost_index(rows: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str], int]:
    counter: Counter[Tuple[str, str]] = Counter()
    for r in rows:
        key = _repost_key(r)
        if key[0] and key[1]:
            counter[key] += 1
    return dict(counter)


def has_salary_signal(row: Mapping[str, Any]) -> bool:
    raw = row.get("job_salary_range")
    if raw is None:
        return False
    parsed = parse_salary_range_string(str(raw))
    if parsed is None:
        return False
    return 0 < parsed < 2_000_000


def _age_factor(age_days: Optional[int]) -> Dict[str, Any]:
    if age_days is None:
        return {
            "key": "age",
            "label": "Posting age unknown",
            "detail": "No usable date on this listing.",
            "points": 10,
        }
    if age_days <= _AGE_BAND_FRESH:
        return {"key": "age", "label": f"Fresh ({age_days}d)", "detail": "Posted within 2 weeks.", "points": 0}
    if age_days <= _AGE_BAND_MILD:
        return {"key": "age", "label": f"Mild ({age_days}d)", "detail": "Between 2 weeks and 1 month old.", "points": 10}
    if age_days <= _AGE_BAND_STALE:
        return {"key": "age", "label": f"Elevated ({age_days}d)", "detail": "Between 1 and 2 months old.", "points": 25}
    return {"key": "age", "label": f"Stale ({age_days}d)", "detail": "Older than 2 months.", "points": 40}


def _repost_factor(count: int) -> Dict[str, Any]:
    if count <= 1:
        return {"key": "repost", "label": "Single listing", "detail": "Not seen repeated in this sample.", "points": 0}
    if count == 2:
        return {"key": "repost", "label": "Repost x2", "detail": "Same role at same company appears twice in sample.", "points": 10}
    return {"key": "repost", "label": f"Repost x{count}", "detail": "Same role at same company repeats in sample.", "points": 20}


def _salary_factor(has_salary: bool) -> Dict[str, Any]:
    if has_salary:
        return {"key": "salary", "label": "Salary disclosed", "detail": "Parseable compensation range on the listing.", "points": 0}
    return {"key": "salary", "label": "No salary disclosed", "detail": "Posting does not expose a usable compensation range.", "points": 15}


def _velocity_placeholder_factor() -> Dict[str, Any]:
    return {
        "key": "velocity",
        "label": "Velocity mismatch (scheduled)",
        "detail": "Requires jobs.last_seen_at; not active in this build.",
        "points": 0,
    }


def ghost_label(score: int) -> str:
    if score >= 50:
        return _LABEL_LOW
    if score >= 25:
        return _LABEL_UNCERTAIN
    return _LABEL_ACTIVE


def compute_ghost_score(
    row: Mapping[str, Any],
    repost_index: Mapping[Tuple[str, str], int],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    try:
        age_days = parse_posting_age_days(row.get("date"), now=now)
        repost_count = int(repost_index.get(_repost_key(row), 1))
        factors: List[Dict[str, Any]] = [
            _age_factor(age_days),
            _repost_factor(repost_count),
            _salary_factor(has_salary_signal(row)),
            _velocity_placeholder_factor(),
        ]
        raw = sum(int(f["points"]) for f in factors)
        score = int(round(raw * 100 / _MAX_RAW_POINTS))
        score = max(0, min(100, score))
        return {"score": score, "label": ghost_label(score), "factors": factors}
    except Exception as exc:
        return {
            "score": 50,
            "label": _LABEL_UNCERTAIN,
            "factors": [
                {"key": "error", "label": "Scoring failed", "detail": f"{type(exc).__name__}: {exc}", "points": 0}
            ],
        }
