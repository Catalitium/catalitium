# Lessons — monolith consolidation

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
