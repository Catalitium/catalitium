# Catalitium: Project Context for Claude

## The Company

Catalitium is a software company. It builds and deploys AI-powered tools and agents for companies that want to move faster, operate leaner, and automate intelligently.

It operates across four areas:

1. **Job Platform.** A solution providing job listings, salary insights, and market data for tech professionals. Companies can post jobs directly through the platform on a single charge or monthly subscription basis.
2. **Market Intelligence.** Deep research reports on AI adoption, salary dynamics, and the structural shifts reshaping software and hiring. Data the tech industry actually needs, sourced and published independently.
3. **Software Development.** Custom AI and automation solutions built for companies that want results without the overhead of traditional development. Fast, lean, and built to last.
4. **AI Agents as a Service (AaaS).** Catalitium builds and deploys AI agents and bots that run business tasks autonomously, replacing manual processes end to end. Subscription-based. Oriented around outcomes, not seats.

**Automation over complexity.**


## Catalitium: Soul, Mission and Values

### Soul
- Move fast. Stay lean. Let AI do the heavy lifting.
- Automation over complexity, outcomes over effort, and intelligence over headcount.
- Direct. Honest. Efficient.

### Mission
- Equip all companies with elite AI. Pros gain market value clarity and upskilling. Tech lifts heavy loads for human purpose.
- We build agents and tools that connect businesses. Faster. Smarter.
- We remove the noise so people can focus on what matters.

### Vision
- AI and tech handles the heavy lifting so humans do the meaningful work.
- Every company gets the tools they need, regardless of size or budget.
- Every professional should know their market value and ways to improve.

---

## Tech Stack

- **Backend**: Flask 3.x (Python 3.11+)
- **Database**: Supabase (PostgreSQL); SQL and pooling via `psycopg` in [app/models/db.py](app/models/db.py)
- **Frontend**: Jinja2 + Tailwind CSS (CDN) under [app/views/templates/](app/views/templates/)
- **Server**: Gunicorn 21.2+
- **Observability**: Google Analytics 4 (gtag.js) + Cookiebot CMP in [app/views/templates/base.html](app/views/templates/base.html); optional `window.catalitiumTrack` for events
- **Deployment**: WSGI-compatible (e.g. Hetzner + Nginx)

### Key Architecture Decisions

- **Postgres as source of truth** for jobs, salary reference, subscribers, auth-adjacent tables
- **Connection pool** with conservative `statement_timeout` for request safety
- **Stateless app tier** for horizontal scaling with Gunicorn
- **Progressive enhancement**: Works without JavaScript; Tailwind for layout

---

## Current Features

### User-Facing
- 🔍 **Smart Job Search**: Title synonyms, fuzzy matching, country normalization
- 💰 **Salary Enrichment**: City → country → global fallback lookup
- 📊 **Delta Badges**: Visual indicators (% difference vs. reference salaries)
- 📧 **Weekly Job Reminders**: Email subscriptions stored in PostgreSQL
- 📄 **Pagination**: Up to 100 results per page (see `PER_PAGE_MAX` in config)

### Analytics & Growth
- 📈 **GA4 (gtag)**: Page and custom events where implemented; consent-gated via Cookiebot
- 🔐 **Minimal Data Collection**: Privacy-first approach

---

## Project Structure

See [README.md](README.md) for the authoritative tree. In short:

- [app/app.py](app/app.py) — routes, rate limits, auth glue
- [app/models/](app/models/) — `db.py` (pool + re-exports), `jobs.py`, `salary.py`, `users.py`, etc.
- [app/views/templates/](app/views/templates/) — Jinja pages and components
- [scripts/](scripts/) — smoke tests (`smoke_db_tables.py`, `supabase_smoke_test.py`, `smoke_routes_http.py`), digest, utilities
- [run.py](run.py) — WSGI entry and local dev server

---

## How Claude Should Approach Catalitium

### Guiding Principles

1. **Respect the Mission**: Every change should equip companies with elite AI and empower tech talent. Automation over complexity.
2. **Simplicity First**: Serve outcomes over effort. Prefer lean, fast tech over bloated architecture.
3. **Quality Over Features**: One polished, outcomes-driven feature beats five half-baked ones.
4. **Data Privacy**: Minimal collection; be direct, honest, and efficient.
5. **Outcome-First Mindset**: UX and engineering decisions center on delivering actionable results (jobs, insights, automation), not engagement loops.

### Common Tasks

**Feature Implementation**
- Add smart search filters (e.g., remote-only, salary range)
- Expand salary enrichment logic (new countries, data sources)
- Improve job detail views and related job recommendations
- Enhance subscription reminder system

**Bug Fixes**
- Search result accuracy (fuzzy matching, synonyms)
- Data sync issues (CSV parsing, salary lookups)
- UI/UX consistency (Tailwind, responsiveness)
- Event tracking accuracy (GA4 / consent where applicable)

**Performance & Reliability**
- Query optimization (PostgreSQL indexes, pool tuning)
- Ingestion / data pipeline outside this repo or scripts
- Job import/sync automation
- Caching strategies for salary data

**Testing & Quality**
- Unit tests for search logic, salary enrichment, filtering
- Integration tests for job search flows
- UI testing for subscription modals, pagination
- Smoke scripts under `scripts/` before release

### Approach to Code Changes

- **Read before changing**: Understand existing patterns before implementing
- **Minimal footprint**: Don't refactor unless absolutely necessary
- **Conservative updates**: Prefer gradual improvements to rewrites
- **Clear commits**: Each commit should solve one clear problem
- **Documentation**: Update this file or README if architecture changes

---

## Key Files & Their Purposes

| File | Purpose |
|------|---------|
| `app/app.py` | Flask app factory; routes for search, job detail, subscriptions, API |
| `app/models/jobs.py` | `Job` model: search, counts, inserts |
| `app/models/salary.py` | Salary table access and parsing helpers |
| `app/models/db.py` | Connection pool, re-exports, shared utilities |
| `app/normalization.py` | Title/country normalization for search |
| `scripts/smoke_*.py` | DB and HTTP smoke checks before deploy |

---

## Development Workflow

### Local Setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

### Running tests and smoke checks
```bash
python -m py_compile app/app.py app/models/db.py app/models/jobs.py run.py
python scripts/smoke_db_tables.py
python scripts/smoke_routes_http.py
# Optional: pytest when a tests/ suite is added
```

### Data updates
- **Jobs / salary**: Production data lives in PostgreSQL; bulk updates via your ingestion pipeline or controlled SQL — not CSV-at-runtime in this codebase.

### Commits
- Branch: `claude/catalitium-*` branches
- Message format: Imperative, clear (e.g., "Add remote filter to job search")
- Include why, not just what

---

## Success Criteria

✅ **Technical**
- Search results are accurate and fast (<200ms)
- Salary enrichment works across 90%+ of jobs
- No broken links or 404s in job details
- GA4 receives expected events where instrumented

✅ **User Experience**
- Job search is intuitive (minimal clicks to find matches)
- Mobile works seamlessly
- Subscription signup is friction-free
- Error messages are helpful, not scary

✅ **Reliability**
- Migrations / imports do not break existing job or salary data
- Subscriptions are reliable (no lost emails)
- No data loss during deployments
- Core search works without third-party APIs at request time (DB-backed)

---

## Common Pitfalls to Avoid

❌ **Over-Engineering**
- Don't add a full admin panel if a CSV upload form suffices
- Don't introduce a cache layer before profiling actual bottlenecks
- Don't switch databases without strong justification

❌ **Scope Creep**
- Don't add recommendation ML models unless A/B tested value is clear
- Don't build social features (messaging, follows) without user demand
- Don't expand to freelance, contractor, or side-gig jobs without clarity

❌ **Data Decisions**
- Don't track user behavior without consent and clear privacy policy
- Don't store passwords or sensitive data; rely on email + token for auth
- Don't assume salary data is perfect; always note data freshness

❌ **UX Mistakes**
- Don't hide search behind a login wall
- Don't auto-play video or use aggressive popups
- Don't make pagination confusing (stay at 100 results/page or explain changes)

---

## Dependencies & Versions

- Python 3.11+
- Flask >= 2.2
- Gunicorn >= 21.2
- python-dotenv >= 1.0

**Why minimal deps?** Fewer dependencies = fewer security updates, fewer bugs, easier deployment.

---

## Extending Catalitium

### Adding a New Filter (Example)
1. Add filter UI in `app/views/templates/index.html`
2. Implement filter logic in `app/models/jobs.py` (`Job._where` / search) and route in `app/app.py`
3. Add smoke or unit coverage for edge cases
4. Instrument GA4 only if product needs the signal (consent-aware)

### Adding a New Data Source
1. Extend the `salary` or `jobs` schema in Supabase as needed
2. Update loaders / ETL outside or inside repo scripts
3. Wire lookups in `app/models/salary.py` or `app/models/jobs.py`
4. Test fallback behavior when the new source is incomplete

---

## Contact & Questions

For clarification on the mission, roadmap, or architectural decisions, check:
- **README.md**: User-facing features & setup
- **LOG_EVENTS_REMOVAL_REVIEW.md**: Why certain event tracking was removed
- **Code comments**: Specific implementation details

---

## License

MIT © 2025 Catalitium

---

*Last updated: April 2026*
*This document is the source of truth for Catalitium's vision and technical direction.*
