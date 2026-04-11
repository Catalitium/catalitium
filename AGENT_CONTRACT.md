# Agent Contract: Three-Worktree Overnight Sprint

This file defines the shared types, file-touch rules, and conventions that all three
parallel feature branches must respect. It exists so that branches merge cleanly into
a single integration branch before landing on `main`.

---

## Canonical data shapes

### CompensationDisplay

Used by **feature/compensation-intelligence** and consumed by any branch that renders
salary information.

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

Used by **feature/company-intelligence-pages**.

```python
CompanyAggregate = {
    "slug": str,                  # url-safe slugified company_name
    "name": str,                  # original company_name
    "job_count": int,
    "locations": list[str],       # distinct country values
    "titles_normalized": list[str],
    "has_salary_data": bool,      # True if any job has salary text or job_salary > 0
    "latest_posting_date": str,   # ISO date string or ""
    "salary_range_display": str | None,
}
```

### ComparisonInput

Used by **feature/candidate-decision-tools**.

```python
ComparisonInput = {
    "job_id": int,
    "title": str,
    "company": str,
    "location": str,
    "salary_min": int | None,
    "salary_max": int | None,
    "currency": str | None,
    "remote": bool,
    "date": str,        # ISO date or raw date string
    "confidence": int,  # 0-100, from CompensationDisplay if available
}
```

---

## File-touch rules

Each branch adds routes to `app/app.py` but MUST use **unique function names and
URL prefixes** to avoid merge conflicts:

| Branch | URL prefix | Route function prefix |
|--------|------------|-----------------------|
| feature/compensation-intelligence | `/compensation/` | `compensation_*` |
| feature/company-intelligence-pages | `/companies/` | `company_*` or rewrite existing `companies` |
| feature/candidate-decision-tools | `/compare/`, `/tracker` | `compare_*`, `tracker` |

### Shared files — touch rules

| File | compensation | company | candidate | Notes |
|------|:-----------:|:-------:|:---------:|-------|
| `app/app.py` | ADD routes | EDIT `/companies` + ADD `/companies/<slug>` | ADD routes | Different sections; low conflict |
| `app/models/jobs.py` | READ only | ADD `company_list`, `company_detail` | READ only | Only company branch extends |
| `app/models/salary.py` | READ only | READ only | READ only | No branch modifies |
| `app/views/templates/components/job_card.html` | ADD confidence badge | DO NOT TOUCH | ADD compare button | **Conflict zone**: both add to card actions |
| `app/views/templates/job_detail.html` | EDIT salary section | DO NOT TOUCH | ADD compare button (header area) | Low conflict (different sections) |
| `app/static/js/main.js` | DO NOT TOUCH | DO NOT TOUCH | ADD compare localStorage + badge | Only candidate branch touches JS |
| `app/views/templates/base.html` | DO NOT TOUCH | DO NOT TOUCH | DO NOT TOUCH | No branch modifies base |

### New files (no conflicts possible)

| Branch | New files |
|--------|-----------|
| compensation | `app/models/compensation.py`, `app/views/templates/compensation_methodology.html`, `tests/test_compensation.py` |
| company | `app/views/templates/company_detail.html`, `tests/test_companies.py` |
| candidate | `app/models/compare.py`, `app/views/templates/compare.html`, `tests/test_compare.py` |

---

## Conventions

- Extend `base.html` for all new templates.
- Use existing Tailwind CDN classes only; no new CSS or JS frameworks.
- No new Python dependencies in `requirements.txt`.
- No new database tables or migrations. Read-only queries on existing schema.
- Feature flags: not required but use conservative guards (`try/except` with fallbacks).
- Each branch creates `PLAN.md` before coding and `HANDOFF.md` after.
- Run `python -m pytest tests/ -v` before declaring done.
- Atomic commits with imperative messages (e.g., "Add compensation confidence engine").
- Carl is always out of scope.

---

*Created: April 2026 | Sprint: Three-Worktree Overnight*
