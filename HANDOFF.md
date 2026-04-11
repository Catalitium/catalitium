# Handoff: feature/smart-discovery-explore

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `PLAN.md` | **EDIT** | Architecture plan for the explore feature |
| `HANDOFF.md` | **EDIT** | This file |
| `app/models/explore.py` | **NEW** | Quality scoring (`compute_quality_score`), function categorization (`categorize_function`), explore aggregations (`get_explore_data`, `get_remote_companies`, `get_function_distribution`) |
| `app/views/templates/explore.html` | **NEW** | Explore Hub page — top titles, locations, companies |
| `app/views/templates/explore_remote.html` | **NEW** | Remote-friendliness company leaderboard |
| `app/views/templates/explore_functions.html` | **NEW** | Function category browser with salary data coverage |
| `tests/test_explore.py` | **NEW** | 32 tests covering quality scoring, function categorization, routes, and filters |
| `app/app.py` | **EDIT** | Added explore imports, `/explore` + `/explore/remote-companies` + `/explore/functions` routes, sitemap entries, `compute_quality_score` wired into `/jobs` item loop, advanced filter params (`remote`, `has_salary`, `freshness`, `function`, `salary_max`) in jobs route |
| `app/models/jobs.py` | **EDIT** | Added `remote`, `has_salary`, `freshness`, `function_cat`, `salary_max` keyword params to `Job._where()` with corresponding SQL clause generation |
| `app/views/templates/components/job_card.html` | **EDIT** | Added quality score badge display |
| `app/views/templates/index.html` | **EDIT** | Added advanced filter panel (remote, has salary, freshness, function category) |
| `app/static/js/main.js` | **EDIT** | Added filter panel state persistence |

## Routes Added

| Route | Function | Method |
|-------|----------|--------|
| `/explore` | `explore_hub` | GET |
| `/explore/remote-companies` | `explore_remote` | GET |
| `/explore/functions` | `explore_functions` | GET |

## Sitemap Entries Added

- `/explore` — priority 0.7, weekly
- `/explore/remote-companies` — priority 0.7, weekly
- `/explore/functions` — priority 0.7, weekly

## Test Results

```
32 passed, 25 warnings in 245.73s (0:04:05)
```

All 32 tests pass:
- 10 unit tests for `compute_quality_score` (complete, empty, partial, numeric salary, date formats, cap, whitespace)
- 13 unit tests for `categorize_function` (Backend, Frontend, Fullstack, ML/AI, DevOps, Data, Product, Security, Other, None, empty, case-insensitive, categories have keywords)
- 3 explore route smoke tests (`/explore`, `/explore/remote-companies`, `/explore/functions`)
- 5 advanced filter smoke tests (`remote=1`, `has_salary=1`, `freshness=7`, `function=Backend`, combined filters)
- 1 sitemap verification (all three explore URLs present)

Warnings are pre-existing `psycopg_pool` deprecation notices and `gotrue` package warnings, unrelated to this branch.

## Known Issues

- Explore aggregation queries (`get_explore_data`, `get_remote_companies`, `get_function_distribution`) hit the live DB. In test mode with no live DB, they gracefully return empty results and render empty-state pages.
- The `freshness` filter uses string interpolation for the interval (`%s days`); the value is validated to `{7, 14, 30}` only, so SQL injection is not possible.
- `ConnectionPool` shutdown warnings in pytest output are a known Python 3.14 / psycopg_pool interaction, not caused by this branch.

## Merge Conflict Zones

Per AGENT_CONTRACT.md:

- **`app/app.py`**: This branch adds routes under `/explore/` prefix with `explore_*` function names. Other Sprint 2 branches use `/salary/` and `/career/` prefixes. The jobs route edit (advanced filter params) is in the `jobs()` function body — only this branch touches that section per contract. Low conflict risk.
- **`app/models/jobs.py`**: Only this branch extends `_where()` with new filter kwargs. Other branches use READ only. No conflict expected.
- **`app/views/templates/index.html`**: Only this branch adds the advanced filter panel per contract. No conflict expected.
- **`app/views/templates/components/job_card.html`**: This branch adds quality/urgency badges. Sprint 1's compare branch added a Compare button (different location in the template). Low conflict risk.
- **`app/static/js/main.js`**: Filter persistence code appended to end of file. Sprint 1's compare branch also appended code. May need trivial merge resolution at file end.
- All new files (`explore.py`, `explore.html`, `explore_remote.html`, `explore_functions.html`, `test_explore.py`) are unique to this branch per contract.

## No New Dependencies

- No new Python packages in `requirements.txt`
- No new database tables or migrations
- Read-only queries on existing `jobs` table only

---

*Completed: April 2026*
