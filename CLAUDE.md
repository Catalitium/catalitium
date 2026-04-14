# CLAUDE.md — Catalitium stack pin

One-page reference for coding agents (Claude Code, Cursor). Read this before touching any file.

## Stack

| Layer | Tech |
|-------|------|
| Web framework | Flask 3.1 (Python 3.11+) |
| Database | Supabase (PostgreSQL via psycopg3 + psycopg-pool) |
| Payments | Stripe (webhooks verified via SDK) |
| Email | SMTP (utils.py `_send_mail`, 3-attempt retry) |
| Frontend | Jinja2 templates + Tailwind CSS (pre-built, committed) |
| Deployment | Gunicorn (gthread) on Hetzner VPS + Nginx |

## App layout

```
app/
  factory.py          — create_app(), middleware, error handlers, template filters. WIRING ONLY.
  config.py           — all constants + env var reads
  utils.py            — shared helpers: API response, spam guards, salary, CSRF, mailer, REPORTS, DEMO_JOBS
  controllers/        — Flask blueprints (routes)
  models/             — DB access (psycopg3 queries, no ORM)
  integrations/       — external service wrappers (CV extraction, etc.)
templates/            — Jinja2 HTML (63 files)
static/               — CSS, JS, images (Tailwind pre-built)
tests/                — pytest suite + smoke scripts
```

## Blueprint registration order

Defined in `app/controllers/__init__.py:ALL_BLUEPRINTS`:

```python
(auth_bp, jobs_bp, carl_bp, carl4b2b_bp, browse_bp, insights_bp, salary_bp, payments_bp, api_bp)
```

**Rule:** New routes go in the matching blueprint. Never add domain routes to `factory.py`.

## Common commands

```bash
# Run app locally
python run.py                            # port 5000

# Tests
pytest tests/ -q                         # full suite (skip smoke)
pytest tests/ -m "not smoke" -q          # unit + integration only
pytest tests/test_catalitium.py -v       # primary test file

# Smoke (requires .env + DB)
python tests/smoke.py --section routes   # HTTP route smoke
python tests/smoke.py --section all      # all sections

# Post-deploy smoke (against prod)
python tests/smoke_prod.py               # requires live catalitium.com
```

## Required env vars

See `.env.example` for full list. Key vars:

| Var | Purpose |
|-----|---------|
| `DATABASE_URL` | Supabase PostgreSQL pooler (session mode) |
| `SECRET_KEY` | Flask session signing (64-char hex) |
| `STRIPE_SECRET_KEY` | Stripe payments |
| `STRIPE_WEBHOOK_SECRET` | Webhook signature verification |
| `ANTHROPIC_API_KEY` | AI job summary endpoint (optional) |
| `SMTP_HOST` | Email — if unset, all emails are skipped silently |

## Key rules

- `factory.py` is wiring-only — no routes, no business logic, ever
- All JSON responses use `api_error_response()` / `api_success_response()` from `utils.py`
- **Exception:** `POST /auth/session` (`auth_session_from_tokens`) uses a small SPA-oriented contract: `{"ok": bool, "error": "...", "redirect": "..."}` — not the `api_fail` envelope. Do not migrate without updating the auth flow JS.
- All SQL is parameterized — no f-string queries
- Secrets only via `os.getenv()` — never hardcoded
- `models/subscribers.py` owns: subscribers, contact-form inserts
- `models/job_orders.py` owns: job postings, Stripe order CRUD
- `models/subscriptions.py` owns: user subscription upsert/lookup
- `models/api_keys.py` owns: API key lifecycle (create/confirm/revoke/quota)
- `models/catalog.py` owns: job search, career intelligence, company queries
- `models/money.py` owns: salary data, PPP, compensation confidence
