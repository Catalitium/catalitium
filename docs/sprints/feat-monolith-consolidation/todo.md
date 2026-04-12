# feat/monolith-consolidation — progress

Branch: `feat/monolith-consolidation` (do not merge to `main` without PR review).

Workflow contract: [claude-rules.md](../claude-rules.md) — use as `@claude-rules.md` before long runs.

## Done this session

- [x] Phase 0 / Item 1 alignment: single import surface `app.utils` for controllers, `factory`, `models/db` normalization re-exports, `catalog`, tests.
- [x] Item 2d (partial): removed `app/app.py`; `run.py`, tests, and scripts import `create_app` from `app.factory`.
- [x] Named TTL caches from `app.utils` wired in `factory.create_app` (`SUMMARY_CACHE`, `AUTOCOMPLETE_CACHE`, `SALARY_CACHE`).
- [x] Removed duplicate inline support block from `factory` (email, datetime, slugify, spam, api envelope) in favor of `app.utils`.
- [x] `scripts/validate_market_reports.py` reads `REPORTS` from `app/factory.py`.
- [x] Verification: `python -m compileall app`, `pytest tests/` — 186 passed, 2 skipped (2026-04-12).
- [x] `docs/sprints/claude-rules.md` — sprint agent contract; `scripts/smoke.py` unified runner (see README).

## Deferred (follow-up PRs)

- [x] **Item 3 (2026-04-12):** `browse.py` (explore+companies), `insights.py` (career), `payments.py` (stripe), `api.py` (api_v1); `ALL_BLUEPRINTS` updated; **88 routes** unchanged; `pytest` green.
- [x] **O1 partial:** Removed `db.py` model/normalization re-exports; `factory` + controllers + `models/__init__.py` import `catalog` / `money` / `identity` directly.
- [ ] Extract blueprints: `auth.py`, `jobs.py`, `carl.py` from `factory.py`.
- [ ] Move `integrations/cv_extract.py` → `models/cv.py`; fold carl mock into blueprint; delete `integrations/`.
- [ ] Strip `models/db.py` re-exports (O1); direct imports across codebase.
- [ ] Controller merges (`browse`, `insights`), renames (`payments`, `api`), R5 internal vs external API split.
- [x] `scripts/smoke.py --section …` unified runner (`db`, `routes`, `carl`, `supabase`, `smtp`, `reports`, `all`).
- [ ] `scripts/digest.py` rename from weekly digest script; E3 magic numbers audit.
- [ ] Route baseline: capture `flask --app run.py routes` output after next large refactor for diffing.

## Review

Consolidation focused on restoring a **green** tree after the merged `utils` module: fixed broken `helpers` / missing `normalization` imports, eliminated the `app.py` shim, and centralized caches. Large factory splits remain intentionally unblocked for smaller commits.
