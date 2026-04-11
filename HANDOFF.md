# HANDOFF — Career Decision Intelligence Tools

**Branch:** `feature/career-decision-intelligence`
**Status:** Complete — 30/30 tests passing
**Date:** April 2026

---

## What Was Built

Six career decision intelligence tools accessible under the `/career/` URL prefix:

| Route | Function | Purpose |
|-------|----------|---------|
| `/career/evaluate` | `career_evaluate` | "Is This Worth It?" job evaluator with 0-100 score |
| `/career/ai-exposure` | `career_ai_exposure` | AI/automation exposure ranking by job function |
| `/career/hiring-trends` | `career_hiring_trends` | Hiring velocity dashboard (hot/cooling/stable companies) |
| `/career/earnings` | `career_earnings` | First-year earnings estimator with comparison bar |
| `/career/paths` | `career_paths` | Career path explorer (promotions, lateral moves, employers) |
| `/career/market-position` | `career_market_position` | Market position benchmarking with percentile gauge |

## Files Created

- `app/models/career.py` — All business logic (7 public functions, helpers)
- `app/views/templates/career_evaluate.html` — Evaluation UI with score gauge
- `app/views/templates/career_ai_exposure.html` — AI exposure table with category badges
- `app/views/templates/career_hiring_trends.html` — Hiring velocity cards grouped by trend
- `app/views/templates/career_earnings.html` — Earnings form with visual salary bar
- `app/views/templates/career_paths.html` — Path explorer with next steps/lateral/employers
- `app/views/templates/career_market_position.html` — Market position form with percentile gauge
- `tests/test_career.py` — 30 tests (unit + route smoke)
- `PLAN.md` — Pre-implementation plan
- `HANDOFF.md` — This file

## Files Modified

- `app/app.py` — Added 6 career routes + 6 sitemap entries
- `app/views/templates/job_detail.html` — Added "Is this role worth it?" link
- `app/views/templates/compare.html` — Added "Evaluate →" link per job

## Architecture

- **No new tables** — Read-only queries on `jobs`, `salary`, `salary_submissions`
- **No new dependencies** — Pure Python logic with existing Flask/psycopg stack
- **Conservative guards** — All DB queries wrapped in try/except with graceful fallbacks
- **Type shapes** — Follows `WorthItScore` and `AIExposure` from AGENT_CONTRACT.md

## WorthItScore Breakdown (each 0-20, total 0-100)

| Dimension | Logic |
|-----------|-------|
| `salary_vs_market` | 20 if posted salary ≥ median, 10 if below, 5 if estimated only, 0 if no data |
| `company_signal` | 20 if 10+ jobs & recent (14d), 10 if 5+, 5 if 2+, 0 otherwise |
| `role_quality` | Up to 20 based on description length + salary transparency + specific location |
| `remote_availability` | 20 if remote, 10 if hybrid, 0 otherwise |
| `alternatives_count` | 20 if 10+ similar roles, 10 if 5+, 5 if 2+, 0 otherwise |

## Test Results

```
30 passed, 0 failed (tests/test_career.py)
```

- 6 WorthItScore unit tests
- 3 AI exposure tests
- 2 hiring velocity tests
- 3 earnings estimator tests
- 2 career paths tests
- 3 market position tests
- 6 route smoke tests (all return 200)
- 2 parameterized route tests (with query params)
- 3 internal helper tests

## Merge Notes

- All routes use unique `/career/*` prefix — no conflicts with other sprint branches
- Only touched `job_detail.html` (added link) and `compare.html` (added link) per AGENT_CONTRACT
- Sitemap entries use priority 0.7, changefreq weekly
- No changes to: `base.html`, `index.html`, `job_card.html`, `main.js`, `companies.html`, `salary_report.html`

---

*Handoff complete. Ready for integration review.*
