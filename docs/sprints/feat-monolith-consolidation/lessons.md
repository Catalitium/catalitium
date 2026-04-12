# Lessons — monolith consolidation

## Patterns to keep

- **Re-export hubs** (`models/db` importing four domains) make the import graph opaque; prefer explicit imports from `catalog` / `money` / `identity` / `utils` when stripping `db.py`.
- **`factory.py` beyond ~500 lines** usually means routes and helpers should move to blueprints and `utils` early, before copy-paste diverges.
- **One utility module** (`app.utils`) needs a complete import sweep in the same commit series as deleting old modules, or CI breaks mid-refactor.

## 2026-04-12

- Merged normalization into `app.utils` but left `db.py` re-exporting from `utils` for compatibility; full O1 should remove that indirection in a dedicated change set.
