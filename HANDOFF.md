# Handoff: feature/candidate-decision-tools

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `PLAN.md` | **NEW** | Architecture plan for the feature |
| `HANDOFF.md` | **NEW** | This file |
| `app/models/compare.py` | **NEW** | Scoring engine: `score_job()`, `compare_jobs()` |
| `app/views/templates/compare.html` | **NEW** | Side-by-side comparison page (extends base.html) |
| `tests/test_compare.py` | **NEW** | 16 tests covering scoring engine + routes |
| `app/app.py` | **EDIT** | Added `/compare` route (`compare_workspace`), `/tracker` route (`tracker`), sitemap entries |
| `app/views/templates/components/job_card.html` | **EDIT** | Added Compare toggle button in actions row |
| `app/static/js/main.js` | **EDIT** | Added compare localStorage logic + floating "Compare Now" FAB |

## Routes Added

| Route | Function | Method |
|-------|----------|--------|
| `/compare` | `compare_workspace` | GET |
| `/tracker` | `tracker` | GET |

## Sitemap Entries Added

- `/tracker` — priority 0.6, weekly
- `/compare` — priority 0.5, weekly

## Test Results

```
16 passed, 10 warnings in 96.11s
```

All 16 tests pass (9 unit tests for scoring engine, 3 for `compare_jobs`, 3 route smoke tests, 1 tracker route test). Warnings are pre-existing psycopg_pool deprecation notices unrelated to this branch.

## Known Issues

- `/compare?ids=...` with valid real job IDs will attempt DB connections for `Job.get_by_id` and `get_salary_for_location`. In test mode with no live DB, these gracefully return empty results (empty state page).
- The compare FAB appears at `bottom-20 md:bottom-6 right-4` to avoid overlap with the mobile bottom nav bar.
- The ConnectionPool shutdown warnings in pytest output are a known Python 3.14 / psycopg_pool interaction, not caused by this branch.

## Merge Notes

- **Conflict zone**: `components/job_card.html` actions row — both this branch and `feature/compensation-intelligence` add elements there. This branch appends the Compare button at the end of the actions div. Compensation adds a confidence badge. Low conflict risk since they target different locations.
- **No conflicts expected**: All new files (`compare.py`, `compare.html`, `test_compare.py`) are unique to this branch per AGENT_CONTRACT.md.
- `app/app.py` routes use unique function names (`compare_workspace`, `tracker`) per contract.
- `main.js` changes are appended at the end of the file; no overlap with other branches.
- No new Python dependencies. No new database tables. Read-only queries only.

---

*Completed: April 2026*
