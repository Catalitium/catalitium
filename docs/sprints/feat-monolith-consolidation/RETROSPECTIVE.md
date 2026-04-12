# Final retrospection — feat/monolith-consolidation (night run)

*Local `claude-rules.md` was not present in this workspace; this document serves as the mandated end-of-run retrospection.*

## What shipped

- **Single utility surface**: All live imports now target `app.utils` for former `helpers`, `api_utils`, `normalization`, `spam_guards`, and `subscriber_fields` usage across controllers, `factory`, `models/db` (re-export block), `models/catalog`, and tests.
- **Factory hygiene**: Removed the large duplicated “support” region (email validation, datetime coercion, slugify, job new/ghost) and redundant imports; `factory` now consumes `utils` plus named module-level caches (`SUMMARY_CACHE`, `AUTOCOMPLETE_CACHE`, `SALARY_CACHE`) instead of constructing new `TTLCache` instances per app.
- **Shim removal**: Deleted `app/app.py`; entrypoints and tests import `create_app` and `safe_parse_search_params` from `app.factory`.
- **Tooling**: `scripts/validate_market_reports.py` now parses `REPORTS` from `app/factory.py`. Removed stray `_patch_utils.py`.
- **Tests**: `pytest tests/` — **186 passed**, 2 skipped (run date in sprint `todo.md`).
- **Docs**: Sprint tracking under `docs/sprints/feat-monolith-consolidation/` (`todo.md`, `lessons.md`, this file).

## What we intentionally did not ship (debt register)

- **Blueprint extraction** (`auth`, `jobs`, `carl`) — `factory.py` remains large; next slices should move routes with per-slice `flask routes` diff vs a saved baseline.
- **O1** full strip of `models/db.py` re-exports — only the normalization source was pointed at `utils`; the rest of the re-export hub remains for minimal churn tonight.
- **Integrations → models**, script merge (`smoke.py --section`), controller renames (`payments`, `api`), E3 magic-number audit — not started; list stays in `todo.md`.

## Staff-engineer bar

- **Approve with conditions**: Import graph is coherent again; tests green; behavior preserved for touched paths. **Condition**: follow-up must shrink `factory` and remove `db` re-exports without another half-merge state.
- **Risk**: Module-level caches are now process-wide singletons (same as before per worker, but shared across app instances in odd test patterns); acceptable for Gunicorn workers.

## Process notes

- **No merge to `main`**: All changes remain on `feat/monolith-consolidation` per operator request; open a PR when awake.
- **Stop / replan trigger**: If the next PR adds blueprints, capture a **route list snapshot** first so missing registrations are obvious.

## One-line takeaway

*Ship the import truth (`utils` + `factory`) before moving thousands of lines of routes—green tests beat a perfect directory tree at 3 a.m.*
