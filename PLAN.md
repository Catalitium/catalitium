# PLAN — Smart Discovery & Explore Hub

**Branch:** `feature/smart-discovery-explore`
**Sprint:** 2 — Levels.fyi Feature Sprint
**Status:** In progress

---

## Goal

Build a smart discovery layer that helps users explore the job market beyond
keyword search: an Explore Hub with top titles/locations/companies, advanced
filters on the existing /jobs page, quality scoring on every card, a
remote-friendliness leaderboard, and a function-category browser.

No new database tables. Read-only queries on existing `jobs` schema.

---

## Deliverables

| # | Deliverable | Route / File | Status |
|---|-------------|-------------|--------|
| A | `app/models/explore.py` — quality score, categorize, explore data, remote companies, function distribution, hiring urgency | New file | Pending |
| B | Explore Hub page | `GET /explore` → `explore.html` | Pending |
| C | Advanced Filter Panel on /jobs | Edit `index.html`, `jobs.py._where()`, `app.py.jobs()` | Pending |
| D | Quality Score badge on job cards | Edit `job_card.html`, `app.py.jobs()` | Pending |
| E | Remote-Friendliness page | `GET /explore/remote-companies` → `explore_remote.html` | Pending |
| F | Function Browse page | `GET /explore/functions` → `explore_functions.html` | Pending |
| G | Route wiring + sitemap | Edit `app.py` | Pending |
| H | Tests (15+) | `tests/test_explore.py` | Pending |

---

## Architecture Decisions

1. **Quality score is computed in Python at render time** — no DB column needed.
   `compute_quality_score(job_dict)` returns a `QualityScore` dict per contract.

2. **Function categorization uses keyword matching on `job_title_norm`** — maps
   to 10 categories + "Other". Pure function, no DB.

3. **Explore data aggregation uses GROUP BY on existing `jobs` table** — three
   queries (top titles, top locations, top companies), cached for the request.

4. **Advanced filters extend `Job._where()`** with optional kwargs:
   `remote`, `has_salary`, `freshness`, `function_cat`, `salary_max`.

5. **No new dependencies** — uses only stdlib + existing Flask/psycopg stack.

---

## File Touch Map

| File | Action |
|------|--------|
| `app/models/explore.py` | CREATE |
| `app/models/jobs.py` | EDIT — extend `_where()` with new filter params |
| `app/app.py` | EDIT — add 3 explore routes, edit jobs() for filters + quality |
| `app/views/templates/index.html` | EDIT — add collapsible advanced filter panel |
| `app/views/templates/components/job_card.html` | EDIT — add quality dot |
| `app/views/templates/explore.html` | CREATE |
| `app/views/templates/explore_remote.html` | CREATE |
| `app/views/templates/explore_functions.html` | CREATE |
| `app/static/js/main.js` | EDIT — add filter localStorage persistence |
| `tests/test_explore.py` | CREATE |
| `PLAN.md` | CREATE (this file) |
| `HANDOFF.md` | CREATE (after implementation) |

---

## Risks & Mitigations

- **Slow aggregation queries:** Use LIMIT and simple GROUP BY; no JOINs.
- **Merge conflicts with other Sprint 2 branches:** Following AGENT_CONTRACT.md
  touch rules strictly — only editing files assigned to this branch.
- **Empty data on fresh installs:** All explore queries use `try/except` with
  empty-list fallbacks.

---

*Created: April 2026*
