# Handoff: feature/salary-intelligence-hub

**Branch:** `feature/salary-intelligence-hub`
**Date:** 2026-04-11

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `PLAN.md` | **NEW** | Architecture plan |
| `HANDOFF.md` | **NEW** | This file |
| `app/models/salary_analytics.py` | **NEW** | Salary intelligence engine: percentile calculator, PPP indices, city comparison, function categorization, benchmarks, trends |
| `app/views/templates/salary_underpaid.html` | **NEW** | "Am I Underpaid?" calculator page |
| `app/views/templates/salary_compare_cities.html` | **NEW** | Cross-city salary comparison with PPP adjustment |
| `app/views/templates/salary_by_function.html` | **NEW** | Function/team salary benchmarks page |
| `app/views/templates/salary_trends.html` | **NEW** | Salary trends visualization page |
| `tests/test_salary_analytics.py` | **NEW** | 34 tests covering analytics engine + routes |
| `app/app.py` | **EDIT** | Added 4 salary intelligence routes, imports, sitemap entries |
| `app/views/templates/salary_report.html` | **EDIT** | Added cross-links to new salary intelligence pages |

## Routes Added

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| GET | `/salary/am-i-underpaid` | `salary_underpaid` | Salary percentile calculator |
| GET | `/salary/compare-cities` | `salary_compare_cities` | Cross-city PPP-adjusted comparison |
| GET | `/salary/by-function` | `salary_by_function` | Function/team salary benchmarks |
| GET | `/salary/trends` | `salary_trends` | Salary trend visualization |

## Test Results

```
34 passed, 12 warnings in 113.69s
```

All 34 tests pass: PPP indices (5), function categorization (14), percentile computation (6), city comparison (3), route smoke tests (6).

## Known Issues

- Salary trends and function benchmarks depend on jobs having `job_salary` (integer) populated. Jobs without numeric salary are excluded from these aggregations.
- PPP indices are hardcoded for ~30 cities; cities not in the list default to 0.75.
- Percentile computation is approximate (based on median comparison, not actual distribution).

## Merge Notes

- All routes under `/salary/` prefix with `salary_*` function names per AGENT_CONTRACT.md.
- Only edits `salary_report.html` (no other branch touches this).
- Only edits `app.py` (different section from other branches).
- No new dependencies, no new tables.

---

*Completed: April 2026 | Sprint 2: Levels.fyi Feature Sprint*
