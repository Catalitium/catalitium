# Agent Contract: Catalitium Worktree Sprints

This file defines the shared types, file-touch rules, and conventions that all
parallel feature branches must respect. It exists so that branches merge cleanly
into a single integration branch before landing on `main`.

---

## Sprint 1 shapes (already merged)

### CompensationDisplay
```python
CompensationDisplay = {
    "source": str,          # "employer" | "estimated" | "crowd" | "unavailable"
    "confidence": int,      # 0-100
    "median": float | None,
    "currency": str | None, # ISO 4217 (EUR, USD, CHF, GBP)
    "range_low": int | None,
    "range_high": int | None,
    "methodology_url": str, # url_for("compensation_methodology")
}
```

### CompanyAggregate
```python
CompanyAggregate = {
    "slug": str, "name": str, "job_count": int,
    "locations": list[str], "titles_normalized": list[str],
    "has_salary_data": bool, "latest_posting_date": str,
    "salary_range_display": str | None,
}
```

### ComparisonInput
```python
ComparisonInput = {
    "job_id": int, "title": str, "company": str, "location": str,
    "salary_min": int | None, "salary_max": int | None,
    "currency": str | None, "remote": bool, "date": str, "confidence": int,
}
```

---

## Sprint 2 shapes (current sprint)

### SalaryPercentile
Used by **feature/salary-intelligence-hub**.
```python
SalaryPercentile = {
    "title": str,
    "location": str,
    "user_salary": float,
    "currency": str,
    "median": float | None,
    "percentile_rank": int,    # 0-100; 50 = at median
    "label": str,              # "above_market" | "at_market" | "below_market"
}
```

### QualityScore
Used by **feature/smart-discovery-explore**.
```python
QualityScore = {
    "total": int,              # 0-100
    "breakdown": {
        "salary": int,         # 0-25
        "description": int,    # 0-25
        "location": int,       # 0-20
        "freshness": int,      # 0-15
        "company": int,        # 0-15
    },
}
```

### WorthItScore
Used by **feature/career-decision-intelligence**.
```python
WorthItScore = {
    "total": int,              # 0-100
    "breakdown": {
        "salary_vs_market": int,
        "company_signal": int,
        "role_quality": int,
        "remote_availability": int,
        "alternatives_count": int,
    },
}
```

### AIExposure
Used by **feature/career-decision-intelligence**.
```python
AIExposure = {
    "function_name": str,
    "exposure_pct": float,     # 0-100
    "category": str,           # "ai-native" | "ai-adjacent" | "ai-distant"
    "job_count": int,
    "median_salary": float | None,
}
```

---

## File-touch rules — Sprint 2

Each branch adds routes to `app/app.py` but MUST use **unique function names and
URL prefixes** to avoid merge conflicts:

| Branch | URL prefix | Route function prefix |
|--------|------------|-----------------------|
| feature/salary-intelligence-hub | `/salary/` | `salary_*` (extend existing) |
| feature/smart-discovery-explore | `/explore/` | `explore_*` |
| feature/career-decision-intelligence | `/career/` | `career_*` |

### Shared files — touch rules (Sprint 2)

| File | salary-hub | discover | career | Notes |
|------|:----------:|:--------:|:------:|-------|
| `app/app.py` | ADD routes | ADD routes + edit `/jobs` filters | ADD routes | Different prefixes |
| `app/models/jobs.py` | READ only | ADD filter methods | READ only | Only discover extends |
| `app/models/salary.py` | READ only | READ only | READ only | No branch modifies |
| `app/views/templates/index.html` | NO | ADD filter panel | NO | Only discover |
| `app/views/templates/components/job_card.html` | NO | ADD quality/urgency badges | NO | Only discover |
| `app/views/templates/job_detail.html` | NO | NO | ADD "worth it" link | Only career |
| `app/views/templates/compare.html` | NO | NO | ADD evaluate link | Only career |
| `app/views/templates/salary_report.html` | ADD links | NO | NO | Only salary-hub |
| `app/static/js/main.js` | NO | ADD filter persistence | NO | Only discover |
| `app/views/templates/base.html` | NO | NO | NO | No branch touches |

### New files (Sprint 2)

| Branch | New files |
|--------|-----------|
| salary-hub | `app/models/salary_analytics.py`, `app/views/templates/salary_underpaid.html`, `salary_compare_cities.html`, `salary_by_function.html`, `salary_trends.html`, `tests/test_salary_analytics.py` |
| discover | `app/models/explore.py`, `app/views/templates/explore.html`, `explore_remote.html`, `explore_functions.html`, `tests/test_explore.py` |
| career | `app/models/career.py`, `app/views/templates/career_evaluate.html`, `career_ai_exposure.html`, `career_hiring_trends.html`, `career_earnings.html`, `career_paths.html`, `career_market_position.html`, `tests/test_career.py` |

---

## Conventions

- Extend `base.html` for all new templates.
- Use existing Tailwind CDN classes only; no new CSS or JS frameworks.
- No new Python dependencies in `requirements.txt`.
- No new database tables or migrations. Read-only queries on existing schema.
- Feature flags: not required but use conservative guards (`try/except` with fallbacks).
- Each branch creates `PLAN.md` before coding and `HANDOFF.md` after.
- Run `python -m pytest tests/ -v` before declaring done.
- Atomic commits with imperative messages (e.g., "Add salary percentile calculator").
- Carl is always out of scope.

---

*Created: April 2026 | Updated: Sprint 2 — Levels.fyi Feature Sprint*
