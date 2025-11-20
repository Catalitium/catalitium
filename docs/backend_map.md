# Backend Map

## Routes
- `GET /` – Renders the main search page. Query params: `title`, `country`, `page` (>=1), `per_page` (<=`PER_PAGE_MAX`). Logs a search event when filters are present. Falls back to demo jobs when no matches are returned.
- `GET /api/jobs` – JSON mirror of the index. Returns `{"items": [...], "meta": {...}}` with pagination metadata. Links present in `BLACKLIST_LINKS` are nulled out.
- `POST /subscribe` – Newsletter opt-in. Accepts JSON (`email`, optional `job_id`) or form data. Returns `{"status": "ok", "redirect": <job_link?>}` on success, `{"error": "duplicate"}` when already subscribed, and `{"error": "invalid_email"}` for bad inputs. Also logs a `log_events` row with `event_type="subscribe"`.
- `POST /events/apply` – Analytics hook for Apply button and other client events. Persists payloads into `log_events` via `insert_search_event`.
- `GET /api/salary-insights` – Lightweight salary feed used by the front-end. Returns `{"count": int, "items": [...], "meta": {...}}`.
- `GET /health` – Readiness probe that performs `SELECT 1`. Responds with `{"status": "ok", "db": "connected"}` or a 503 error payload.
- Error handlers emit JSON: 404 -> `{"error": "not found"}`, 500 -> `{"error": "internal error"}` (with logging).

## Models & DB Helpers (`app/models/db.py`)
- `get_db()` – Returns a per-request connection (psycopg when configured, SQLite when forced).
- `close_db()` – Closes the cached connection at teardown.
- `init_db()` – Ensures required tables and indexes exist for both backends.
- `Job.count(...)`, `Job.search(...)`, `Job.get_link(...)`, `Job.insert_many(...)` – Core job data helpers.
- `insert_subscriber(...)` – Inserts emails into `subscribers`, returns `"ok"`, `"duplicate"`, or `"error"`.
- `insert_search_event(...)` – Unified analytics logger for search/apply/subscribe/filter events.
- `insert_subscribe_event(...)` – Convenience wrapper that funnels subscribe analytics into `insert_search_event`.
- Parsing helpers: `parse_salary_query`, `normalize_title`, `normalize_country`, `_coerce_datetime`, `_job_is_new`, `_to_lc`.

## Environment Variables
- `SECRET_KEY` – Required; app aborts if unset or default placeholder.
- `SUPABASE_URL` / `DATABASE_URL` – Primary Postgres DSN. If missing and `FORCE_SQLITE` is falsy the app exits.
- `FORCE_SQLITE` – Forces the bundled SQLite database (used in tests/local dev).
- `ENV` / `FLASK_ENV` – Controls production toggles such as template reload and secure cookies.
- `ANALYTICS_SALT`, `ANALYTICS_SESSION_COOKIE` – Configure analytics hashing and the cookie used for session tracking.
- `DB_PATH` – Override SQLite file path when `FORCE_SQLITE` is enabled.
- `GTM_CONTAINER_ID` – Injected into `base.html` when defined; keeps GA4 snippet dynamic.
- `FLASK_HOST`, `PORT`, `FLASK_PORT`, `FLASK_DEBUG` – Runtime overrides honoured by `run.py`.

## Request & Response Invariants
- Pagination clamped to `page >= 1` and `1 <= per_page <= PER_PAGE_MAX`. Display metadata floors small values at 10 for readability.
- `parse_salary_query` strips inline salary hints while capturing numerical ranges for analytics.
- Apply analytics fall back to `"N/A"` titles/countries when missing to keep rows queryable.
- `Job.search` never surfaces links contained in `BLACKLIST_LINKS`.
- `_job_is_new` flags jobs posted within the last two days (UTC aware).
- Subscribe JSON responses intentionally return 200 + `"duplicate"` to avoid leaking subscriber status.

## Known Caveats & Side Effects
- Unique constraint on `Jobs.link`; duplicates are skipped silently.
- `insert_search_event` is best effort; failures log at DEBUG and continue.
- Demo jobs render only when both filters are empty and the query returns no matches.
