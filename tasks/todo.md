## Plan

- [x] **Phase 1 — Local mechanical checks** (repo root; `.env` with `DATABASE_URL`)
- [x] **Phase 2 — Prod env checklist** (operator confirmed: `prod.env`, limits, rate limit, keys)
- [x] **Phase 3 — Smoke** — local `smoke_routes_http.py` passed; prod spot checks below
- [x] **Phase 4 — Docs / hygiene** — `README.md`, `CLAUDE.md`, `.env.example`, smoke scripts aligned

## Prod env checklist (operator — confirm on server)

| Area | Verify |
|------|--------|
| Core | `DATABASE_URL`, `SECRET_KEY`, `ENV=production` or `FLASK_ENV=production`, `FLASK_DEBUG=0` |
| URLs | `BASE_URL=https://catalitium.com` (emails, sitemap, external links) |
| HTTP | HTTPS termination, `TRUSTED_HOSTS` if used behind Nginx, `SESSION_COOKIE_SECURE` on |
| Limits | `MAX_CONTENT_LENGTH` aligned with Nginx `client_max_body_size` (5 MiB app default if unset) |
| Stripe | Live keys + webhook secret match Dashboard |
| Rate limit | Gunicorn workers >1 → `RATELIMIT_STORAGE_URI=redis://...` if limiter must be shared |

## Post-deploy smoke (operator)

**Local / CI (Flask `test_client`):**

```bash
python scripts/smoke_routes_http.py
```

**Production (curl examples):**

```bash
curl -sS -o /dev/null -w "health:%{http_code}\n" https://catalitium.com/health
curl -sS -o /dev/null -w "jobs:%{http_code}\n" https://catalitium.com/jobs
curl -sS -o /dev/null -w "jobs_salary_min:%{http_code}\n" "https://catalitium.com/jobs?salary_min=80000"
curl -sS -o /dev/null -w "sitemap:%{http_code}\n" https://catalitium.com/sitemap.xml
```

Re-check `jobs_salary_min` after each deploy (must be **200**). If it is **500**, inspect Gunicorn/journal logs for the traceback, confirm `jobs.job_salary` exists (`init_db()` runs at startup and runs `ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_salary INTEGER`), and confirm the live revision matches `main`.

## Progress

### Phase 1 (2026-04-11)

- [x] `python -m py_compile app/app.py app/models/db.py app/models/jobs.py app/config.py app/models/salary.py app/api_utils.py run.py scripts/smoke_routes_http.py` → exit 0
- [x] `python scripts/smoke_db_tables.py` → exit 0
- [x] `python scripts/supabase_smoke_test.py` → exit 0 (11/11)
- [x] `python scripts/smoke_routes_http.py` → exit 0 (`/health`, `/jobs`, `salary_min` view, sitemap, job detail)
- [x] `python scripts/smoke_carl_pdf_profile.py` → exit 0 (extract + POST 200; DB row check optional via `CARL_TEST_USER_ID`)
- [x] `_get_demo_jobs()` payload aligned with job card / index expectations (avoids sparse keys on empty-search fallback)

### Phase 2

- [x] Operator: `prod.env` / Hetzner checklist completed (per your confirmation)

### Phase 3 (production spot checks, 2026-04-11)

- [x] `GET https://catalitium.com/health` → **200**
- [x] `GET https://catalitium.com/sitemap.xml` → **200**
- [x] `GET https://catalitium.com/jobs` → **200**
- [x] **`GET https://catalitium.com/jobs?salary_min=80000` → 200** (post-deploy; `pwsh -File scripts/smoke_prod.ps1` exit 0)

### Phase 4

- [x] `CLAUDE.md` — stack, GA4, Postgres, smoke scripts (no stale GTM/SQLite-only narrative)
- [x] `README.md` — project tree + pre-deploy smoke commands
- [x] `.env.example` — commented smoke script invocations

## Review

Production deploy verified **2026-04-11**: `scripts/smoke_prod.ps1` all green. Re-run that script after each future deploy.
