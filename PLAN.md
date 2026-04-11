# Compensation Intelligence — Architecture Plan

**Branch:** `feature/compensation-intelligence`
**URL prefix:** `/compensation/`
**Route function prefix:** `compensation_*`

---

## Goal

Upgrade flat salary numbers into transparent, trust-building compensation views.
No new tables, no new dependencies. Read-only queries on existing schema.

## Data Sources (read-only)

| Table | Fields used |
|-------|-------------|
| `jobs` | `salary` (text range), `job_salary` (int), `location`, `city`, `country` |
| `salary` | `median_salary`, `currency`, `city`, `region`, `country` |
| `salary_submissions` | `job_title`, `company`, `location`, `base_salary`, `currency` |

## Architecture

### Compensation confidence scoring

Pure Python function: `compute_compensation_confidence(job_row, salary_ref_result, has_crowd_data) -> CompensationDisplay`

Scoring (0-100):
- Employer salary text present: **+40**
- Estimated from city-level reference: **+30**, country-level: **+15**, global/fallback: **+5**
- Crowd-sourced match exists: **+15**
- Location match specificity bonus: **+10** (city match) / **+5** (region)

Source label: `"employer"` > `"estimated"` > `"crowd"` > `"unavailable"`

### Integration

- `job_detail` route: call engine after salary enrichment, pass `CompensationDisplay` to template
- `jobs` listing route: compute confidence per job (using cached salary data), attach to item payload
- Templates consume `comp_display` dict for badge color + source label

## Files

### New files
| File | Purpose |
|------|---------|
| `app/models/compensation.py` | Confidence scoring engine |
| `app/views/templates/compensation_methodology.html` | Static methodology page |
| `tests/test_compensation.py` | Unit + route tests |
| `PLAN.md` | This file |
| `HANDOFF.md` | Post-implementation handoff |

### Modified files
| File | Change |
|------|--------|
| `app/app.py` | Import engine, wire into `job_detail` and `jobs`, add `/compensation/methodology` route, add to sitemap |
| `app/views/templates/job_detail.html` | Confidence badge + source label in salary section |
| `app/views/templates/components/job_card.html` | Small confidence indicator next to estimated salary |

### Untouched (per contract)
- `app/static/js/main.js`
- `app/views/templates/base.html`
- `app/views/templates/companies.html`
- `app/models/jobs.py` (read-only)
- `app/models/salary.py` (read-only)

## Route

| Path | Function | Method |
|------|----------|--------|
| `/compensation/methodology` | `compensation_methodology` | GET |

---

*Created: April 2026 | Sprint: Three-Worktree Overnight*
