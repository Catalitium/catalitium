# feat/monolith-consolidation — progress

Branch: `feat/monolith-consolidation` (do not merge to `main` without PR review).

## SPRINT COMPLETE — 2026-04-12

**Baseline locked:** factory.py = 2821 lines, 88 routes, integrations/ existed.

## All tasks done

- [x] Phase 0 / Item 1 — `app/utils.py` unified (5 modules merged); `app/app.py` removed; named caches wired.
- [x] BETA_1 — `app/models/db.py` re-export audit confirmed clean; no re-export hub existed.
- [x] ALPHA_1 — `carl_mock_analysis.py` inlined into `carl.py`; `app/integrations/` deleted; `app/routes/` and `app/services/` cleaned; test imports fixed.
- [x] ALPHA_2 — `app/controllers/auth.py` extracted from `factory.py` (~780 lines moved); `auth_bp` first in `ALL_BLUEPRINTS`; url_for → `auth.*` sweep; limiter wraps applied.
- [x] ALPHA_3 — `app/controllers/jobs.py` extracted from `factory.py` (~1600 lines moved); `jobs_bp` second; url_for → `jobs.*` sweep; limiter on jobs endpoints; `_query_jobs_payload` un-nested; Jinja global `job_url` updated to `jobs.job_detail`.
- [x] ALPHA_4 — `factory.py` verified wiring-only: **364 lines**, zero `@app.get/post/route`, stale comment removed.
- [x] PR gate: `pytest tests/` → 186 passed, 2 skipped; `compileall` clean; 88 routes; smoke routes OK.

## Final architecture

```
app/
  factory.py          364 lines  — wiring only (extensions, hooks, filters, errors)
  utils.py                       — all shared helpers
  market_reports_data.py         — REPORTS catalog (data module)
  config.py                      — all constants + env vars
  controllers/
    __init__.py        ALL_BLUEPRINTS = (auth, jobs, carl, browse, insights, salary, payments, api)
    auth.py            auth, profile, hire, studio, docs routes + supabase helpers
    jobs.py            search, job detail, API, subscribe, sitemap, static utils
    carl.py            carl + market research (carl_mock_analysis inlined)
    browse.py          explore + companies
    insights.py        career tools
    salary.py          salary analytics
    payments.py        stripe routes
    api.py             external API v1
  models/
    catalog.py         jobs, taxonomy, explore
    db.py              pool, get_db/init_db/close_db, logger
    identity.py        API keys, subscriptions, auth
    money.py           salary data
    cv.py              CV extraction (moved from integrations/)
  data/
    demo_jobs.csv      used by _get_demo_jobs() in jobs.py
```

## Next step

Open PR from `feat/monolith-consolidation` → `main`.
Run `pytest tests/ -q` one final time before merge per `claude-rules.md`.
