# Catalitium Architecture Documentation

## Overview
Catalitium is a job search platform with salary insights, built with Flask using a clean MVC architecture.

## Directory Structure

```
/catalitium
  /app                      # Main application package
    __init__.py             # Package marker
    app.py                  # Flask application factory and routes
    /models                 # Data layer
      __init__.py
      db.py                 # Database connections, query helpers, analytics
    /views                  # Presentation layer
      __init__.py
      /templates            # Jinja templates (base, index, legal, components)
    /static                 # Front-end assets
  /data                     # SQLite snapshot for local runs
    catalitium.db
  /docs                     # Project documentation
  /tests                    # Pytest suite
  requirements.txt          # Python dependencies
  .env                      # Environment variables (not in git)
```

## Core Components

### 1. Application Module (`app/app.py`)
**Purpose**: Creates and configures the Flask application and houses all routes.

**Key Functions**:
- `create_app()` - Initializes Flask, applies security defaults, and wires teardown hooks.
- `_resolve_pagination()` / `_display_per_page()` - Clamp pagination inputs to safe bounds.
- `_job_is_new()` / `_coerce_datetime()` / `_to_lc()` - Formatting helpers reused across responses.

**Routes**:
- `GET /` (`index`) - Main search page; logs analytics through `insert_search_event`.
- `GET /api/jobs` (`api_jobs`) - JSON mirror of the search results with pagination metadata.
- `POST /subscribe` (`subscribe`) - Accepts JSON or form submissions, uses `insert_subscriber` and `insert_subscribe_event`.
- `POST /events/apply` (`events_apply`) - Analytics endpoint backing apply clicks and client events via `insert_search_event`.
- `GET /api/salary-insights` (`api_salary_insights`) - Lightweight salary dataset for client consumption.
- `GET /health` (`health`) - Readiness probe that verifies database connectivity.
- `GET /legal` (`legal`) - Static legal page.
- Error handlers for 404 and 500 emit JSON payloads and log failures.

### 2. Models Layer (`app/models/db.py`)
**Purpose**: Data access, query helpers, and analytics logging.

#### Database Functions
- `get_db()` - Acquire a per-request connection (psycopg when configured, SQLite when forced).
- `close_db()` - Close the cached connection at teardown.
- `init_db()` - Ensure tables and indexes exist for both backends.
- `Job.count(...)`, `Job.search(...)`, `Job.get_link(...)`, `Job.insert_many(...)` - Query helpers for the `jobs` table.

#### Analytics
- `insert_search_event(...)` - Records search/apply/filter/subscribe analytics entries.
- `insert_subscribe_event(...)` - Convenience wrapper that annotates subscription attempts.
- `_hash()`, `_ensure_session_id()`, `_client_meta()` - Privacy helpers for analytics payloads.

#### Parsing & Formatting
- `parse_salary_query()`, `normalize_title()`, `normalize_country()` - Clean and standardize request filters.
- `parse_job_description()`, `clean_job_description_text()`, `summarize_two_sentences()` - Prepare job descriptions for display.
- `format_job_date_string()` - Render date strings for templates and API responses.

### 3. Views Layer (`app/views/templates/`)
**Purpose**: HTML templates for rendering.

- `base.html` - Base layout with header, footer, navigation, and GA4 instrumentation.
- `index.html` - Search form, pagination controls, and job results grid.
- `legal.html` - Combined privacy policy and terms.
- `components/` - Shared template fragments (buttons, analytics payload script, etc.).

**Template Variables**:
- `results` - List of job dictionaries.
- `count` - Total number of results.
- `title_q` - Normalized title query displayed in the UI.
- `country_q` - Normalized country code shown in the UI.
- `pagination` - Pagination metadata dictionary consumed by templates.

## Data Flow

### Search Request Flow
```
1. User enters search -> GET /?title=engineer&country=de
2. app.app.index() receives request
3. Parse salary from title -> parse_salary_query()
4. Normalize inputs -> normalize_title(), normalize_country()
5. Fetch jobs from Postgres -> Job.search()
6. Shape rows for the template (format dates, sanitize links)
7. Log analytics -> insert_search_event() (best-effort; failures are swallowed)
8. Render template -> render_template("index.html")
```

### Database Connection Flow
```
1. Request starts -> get_db() called
2. get_db() opens a psycopg connection (autocommit)
3. Connection is cached on flask.g for the duration of the request
4. Request ends -> close_db() closes the connection
```

## Environment Variables

Required:
- `SECRET_KEY` - Flask secret key (must be set, no default)

Optional:
- `DATABASE_URL` - Primary PostgreSQL connection string
- `SUPABASE_URL` - Legacy alias for Postgres DSN (normalized at startup)
- `FORCE_SQLITE` - Force the bundled SQLite database (used in tests/local dev)
- `ENV` / `FLASK_ENV` - Controls production toggles (template reload, cookie security)
- `GTM_CONTAINER_ID` - Google Tag Manager ID embedded in `base.html`
- `ANALYTICS_SALT` - Salt used when hashing analytics payloads
- `ANALYTICS_SESSION_COOKIE` - Cookie name for analytics session tracking
- `DB_PATH` - Override path to the SQLite database file
- `FLASK_HOST`, `PORT`, `FLASK_PORT`, `FLASK_DEBUG` - Runtime overrides in `run.py`

## Database Schema

Managed through Postgres migrations (Jobs, subscribers).

## Error Handling

### Database Errors
- Postgres connection failures -> surfaced and logged during startup
- Duplicate email subscriptions -> Gracefully handled with success message

### User Input Errors
- Invalid email -> Flash error message, redirect
- Invalid search params -> Treated as empty search
- Out of range pagination -> Clamped to valid range

## Security Features


1. **Secret Key Enforcement**: App refuses to start without a valid `SECRET_KEY`.
2. **Email Validation**: RFC-compliant validation via `email-validator`.
3. **SQL Injection Protection**: Parameterized queries throughout the data layer.
4. **Privacy**: IP addresses, user agents, and email addresses are hashed before analytics storage.
5. **Analytics Session Cookies**: Server-issued IDs set with secure, HTTP-only, same-site attributes.
6. **CSRF Protection**: Flask session management mitigates cross-origin form posts.

## Performance Optimizations

1. Postgres indexes on frequently queried columns
2. Server-side pagination to limit result size
3. Autocommit connections to avoid long-running transactions

## Testing


See `tests/` for pytest coverage across:
- Search functionality
- Query parsing
- Data filtering
- Pagination
- Database connections
- Subscription flow

Run tests: `pytest -q`

## Known Limitations

1. No authentication: all routes are public and rely on obscurity for admin-style actions.
2. Limited search: No full-text search, simple filters only
3. Analytics tables can grow without archival policies

## Future Improvements


1. Move to proper database (PostgreSQL) for jobs data
2. Add Elasticsearch for advanced search
3. Implement user accounts and saved searches
4. Add email notification system
5. API rate limiting and authentication
6. Comprehensive test coverage
7. Docker containerization
8. CI/CD pipeline







