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

## Stream S2 (scripts)

- Owner: `scripts/smoke.py` — either keep subprocess wrapper or inline `main()` from legacy scripts per [PLAN_ITEMS_2_4.md](PLAN_ITEMS_2_4.md).
- Owner: `send_weekly_digest.py` → `digest.py` + doc/cron references.
- **Do not delete** `smoke_prod.ps1` without ops sign-off.

## Stream S3 (factory extraction) — single owner

Slice order from plan: **2a auth** → **2b jobs** → **2c carl** → **2d slim factory**.

After each slice:

```bash
python -c "from app.factory import create_app; app=create_app(); print(len(list(app.url_map.iter_rules())), 'routes')"
python -m pytest tests/ -q
```

Baseline route count must match pre-slice (record in `todo.md`).

## Stream S4 (O1 `db.py`)

- Mechanical: replace `from app.models.db import Job` → `from app.models.catalog import Job`, etc.
- Remove re-export blocks at end of `db.py`.
- Run full test suite; watch **circular imports** (`utils` ↔ `models`).

## Communication

- Append progress + route count to [todo.md](todo.md).
- On failure or scope creep: append [lessons.md](lessons.md) and stop.
