# Agents

## Cursor Cloud specific instructions

### Quick reference

| Action | Command |
|--------|---------|
| Install deps | `pip install -r requirements.txt && pip install "pytest>=8" "pytest-cov>=5" "httpx>=0.27"` |
| Run unit tests | `SECRET_KEY="ci-test-secret-key-not-for-production" DATABASE_URL="" FLASK_ENV=testing python3 -m pytest tests/ -m "not smoke" --cov=app --cov-report=term-missing` |
| Compile check | `python3 -m compileall app/ tests/ -q` |
| Start dev server | `FLASK_ENV=development python3 run.py` (serves on `http://localhost:5000`) |

### Environment setup

- Copy `.env.example` to `.env` and fill in values. For local dev without a real database, set `DATABASE_URL` to a fake Postgres URL (e.g. `postgresql://127.0.0.1:65534/dev_nonexistent`). The app will start but DB-dependent features will degrade gracefully.
- `SECRET_KEY` is auto-generated for non-production envs if not set in `.env` (see `run.py`).
- Set `FLASK_ENV=development` for debug mode and template auto-reload.

### Caveats

- **psycopg_pool background retries**: When `DATABASE_URL` points to an unreachable host, `psycopg_pool.ConnectionPool(min_size=1)` retries connections in a background thread, filling logs with warnings. This is harmless — the Flask server still serves pages. Pages that require DB queries will return errors or fallback/demo data.
- **Test speed without DB**: Unit tests (CI config: `DATABASE_URL=""`) take ~10 minutes because each test creating a Flask `app` fixture triggers a pool connection attempt that takes several seconds to time out. Three tests (`test_http_health_ok`, `test_http_x_request_id_header`, `test_http_health_deep_includes_db_latency`) fail without a real DB — this is expected.
- **No formal linter config**: The repo has no `pyproject.toml`, `.flake8`, or `ruff.toml`. CI only runs pytest. `python3 -m compileall` is a quick syntax check.
- **Tailwind CSS is pre-built**: `app/static/css/tailwind.css` is committed. Node/npm is only needed when adding new Tailwind utility classes (run `npm install && npm run build:css` from `app/static/css/`).
- **External services** (Supabase, Stripe, SMTP, Anthropic) are optional for local dev. See `.env.example` for all env vars. Without them: auth flows, payments, emails, and AI summaries will not work, but job browsing, explore, market research, and registration pages render fine.
