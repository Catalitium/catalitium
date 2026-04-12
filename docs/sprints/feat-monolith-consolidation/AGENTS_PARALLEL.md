# Parallel agent workstreams — monolith Items 2–4

Read [@docs/sprints/claude-rules.md](../claude-rules.md) first. Branch: **`feat/monolith-consolidation`**. Do not merge to `main` without PR.

## Merge order (avoid `factory.py` conflicts)

| Order | Stream | Owns primarily | Blocks |
|-------|--------|----------------|--------|
| 1 | **S1 — Controllers surface** | `app/controllers/*`, `__init__.py`, templates `url_for` | Nothing (landed: browse, insights, payments, api) |
| 2 | **S2 — Scripts** | `scripts/smoke.py`, digest rename, README / `.env.example` | Nothing vs S1 |
| 3 | **S3 — Factory extraction (serial)** | `app/factory.py` → `auth.py`, `jobs.py`, `carl.py` | **One agent at a time** on `factory.py` |
| 4 | **S4 — Models O1** | `app/models/db.py` + import rewires across app/tests | After S3 or coordinate: touching same files as S3’s new blueprints causes conflicts |

**Rule:** Only **one** agent edits `factory.py` per PR. S1 and S2 can run in parallel branches; rebase onto latest `feat/monolith-consolidation` before merge.

## Stream S1 (controllers) — DONE baseline 2026-04-12

- Merged `explore` + `companies` → **`browse`** (`browse_bp`).
- Renamed `career` → **`insights`** (`insights_bp`), URLs unchanged (`/career/...`).
- Renamed `stripe_routes` → **`payments`** (`payments_bp`).
- Renamed `api_v1` → **`api`** (`api_bp`).
- Templates + `factory` sitemap `url_for` updated; nav active state for pricing uses **`payments.pricing`**.

**Follow-up for next agent:** grep stale blueprint names; run `pytest` + `python scripts/smoke.py --section routes`.

## Stream S2 (scripts) — DEFERRED

Not executed in this sprint. Optional follow-up:
- `send_weekly_digest.py` → rename to `digest.py`
- `smoke_prod.ps1` — keep until explicit ops sign-off

## Stream S3 (factory extraction) — DONE 2026-04-12

All slices complete:
- **ALPHA_1 (2c):** `carl_mock_analysis.py` inlined into `carl.py`; `app/integrations/` deleted
- **ALPHA_2 (2a):** `app/controllers/auth.py` extracted; `auth_bp` registered first
- **ALPHA_3 (2b):** `app/controllers/jobs.py` extracted; `jobs_bp` registered second
- **ALPHA_4 (2d):** `factory.py` = 364 lines, zero domain routes

Final `ALL_BLUEPRINTS` order: `(auth_bp, jobs_bp, carl_bp, browse_bp, insights_bp, salary_bp, payments_bp, api_bp)`

## Stream S4 (O1 `db.py`) — CONFIRMED CLEAN

Audit confirmed `db.py` had no re-export hub to strip. Controllers import directly from `catalog`, `money`, `identity` — only `logger`, `get_db`, `parse_job_description`, `upsert_profile_cv_extract`, `SECRET_KEY`, `SUPABASE_URL` imported via `db.py` (all correctly owned there).

## Sprint status: READY FOR PR

Run `pytest tests/ -q` once before merging to `main`.
