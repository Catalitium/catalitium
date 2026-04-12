# Lessons — monolith consolidation

## BASELINE — resurrection pre-flight (2026-04-12)

- **Branch:** `feat/monolith-consolidation`
- **app/factory.py:** 2537 lines (PowerShell line count)
- **Route count (locked):** 88 routes (`create_app().url_map`)
- **app/data/:** retained — contains `demo_jobs.csv` (used by `_get_demo_jobs` in factory)
- **app/routes/, app/services/:** remove if empty during ALPHA_1 scaffold cleanup

## 2026-04-12 | BETA_1 | models/db.py re-export audit | line delta 0

- Confirmed [app/models/db.py](app/models/db.py) ends at `parse_job_description` with **no** trailing re-export hub; consumers already import `catalog` / `money` / `identity` from true owners. No `factory.py` edits per stream rules.

## 2026-04-12 | ALPHA_1 | inlined carl_mock into controllers/carl.py; removed app/integrations/ | carl.py +~540 lines, integrations -2 files

## 2026-04-12 | ALPHA_2 | auth blueprint + templates url_for auth.* | factory.py -469 lines (approx)

## 2026-04-12 | ALPHA_3 | jobs blueprint (`app/controllers/jobs.py`): landing, /jobs, APIs, subscribe/contact, sitemap, static well-known; `ALL_BLUEPRINTS` order auth → jobs → carl → browse…; `demo_jobs.csv` via `Path(__file__).resolve().parent.parent / "data"`; factory wiring-only ~366 lines; route count 88 unchanged

## 2026-04-12 | ALPHA_4 | (same push as ALPHA_3) factory gate: `wc -l` ~366, `rg '@app\\.(get|post|route)'` → 0; remaining `@app` hooks only (before/after request, errors, filters)

## Patterns to keep

- **Re-export hubs** (`models/db` importing four domains) make the import graph opaque; prefer explicit imports from `catalog` / `money` / `identity` / `utils` when stripping `db.py`.
- **`factory.py` beyond ~500 lines** usually means routes and helpers should move to blueprints and `utils` early, before copy-paste diverges.
- **One utility module** (`app.utils`) needs a complete import sweep in the same commit series as deleting old modules, or CI breaks mid-refactor.

## 2026-04-12

- Merged normalization into `app.utils` but left `db.py` re-exporting from `utils` for compatibility; full O1 should remove that indirection in a dedicated change set.

## 2026-04-12 (smoke + rules)

- One **`scripts/smoke.py --section`** entry point reduces “which script did we run?” drift; document it in README and `.env.example` so operators find it.

## 2026-04-12 (parallel agents + Item 3 + O1)

- **`app/models/__init__.py`** still re-exported `Job` from `db` after stripping `db.py` — tests import `app.models` first and exploded. After O1, re-export hub must be updated **the same commit** as `db.py` cuts.
- Blueprint rename (`stripe_routes` → `payments`) requires **`request.endpoint`** fixes (`payments.pricing`), not bare `pricing`.
