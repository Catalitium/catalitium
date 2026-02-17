# Catalitium: Project Context for Claude

## Mission Statement

**Catalitium exists to equip tech talent with the tools, insights, and clarity they need to navigate and shape the future of work in AI, automation, and software.**

---

## Project Overview

Catalitium is a **high-signal job board** that prioritizes search-first UX and high-quality job alerts for tech professionals. We solve the noise problem in job search by providing:

- **Smart, contextual job discovery** tailored to individual career goals
- **High-quality alerts** that respect users' time and attention
- **Salary transparency** and market insights for informed career decisions
- **Future-proofing resources** for navigating AI and automation in tech careers

### Core Value Proposition

Tech talent spends hours filtering irrelevant job postings. Catalitium eliminates noise through intelligent search, relevant filtering, and thoughtful alerts—allowing professionals to focus on opportunities that truly matter for their growth.

---

## Tech Stack

- **Backend**: Flask 2.2+ (Python 3.11+)
- **Database**: SQLite (lightweight, low-ops)
- **Data**: CSV files (jobs.csv, salary.csv, jobs-active.csv, salary.csv)
- **Frontend**: HTML + Tailwind CSS (CDN-based)
- **Server**: Gunicorn 21.2+
- **Observability**: Google Tag Manager (GTM) for event tracking
- **Deployment Ready**: WSGI-compatible for cloud platforms

### Key Architecture Decisions

- **Flat file approach**: CSV data for simplicity and transparency
- **Zero-config setup**: SQLite auto-creates schema on first run
- **Stateless design**: Easy horizontal scaling with Gunicorn
- **Progressive enhancement**: Works without JavaScript, enhanced with Tailwind

---

## Current Features

### User-Facing
- 🔍 **Smart Job Search**: Title synonyms, fuzzy matching, country normalization
- 💰 **Salary Enrichment**: City → country → global fallback lookup
- 📊 **Delta Badges**: Visual indicators (% difference vs. reference salaries)
- 📧 **Weekly Job Reminders**: Email subscriptions stored in SQLite
- 📄 **Pagination**: 100 results per page for fast browsing

### Analytics & Growth
- 📈 **GTM Event Tracking**: Search, views, subscriptions logged for insights
- 🔐 **Minimal Data Collection**: Privacy-first approach

---

## Project Structure

```
catalitium/
├── app/                          # Main Flask application package
│   ├── app.py                   # Flask app factory & configuration
│   ├── db.py                    # SQLite initialization & queries
│   ├── models.py                # Data models (jobs, salary, subscriptions)
│   ├── search.py                # Smart search logic (fuzzy, synonyms, filters)
│   ├── salary_utils.py          # Salary enrichment & delta calculations
│   ├── gtm_events.py            # Google Tag Manager event handling
│   ├── templates/               # Jinja2 HTML templates
│   │   ├── base.html            # Layout wrapper
│   │   ├── index.html           # Homepage & search UI
│   │   ├── job_detail.html      # Single job view
│   │   └── subscription_modal.html
│   ├── static/
│   │   ├── css/                 # Custom styles (Tailwind overrides if any)
│   │   ├── js/                  # Minimal JavaScript (progressive enhancement)
│   │   └── images/              # Logos, favicons, etc.
│   ├── migrations/              # SQLite schema migrations (if applicable)
│   └── config.py                # Environment-based configuration
├── jobs.csv                      # Job listings data
├── salary.csv                    # Salary reference data
├── requirements.txt              # Python dependencies
├── run.py                        # Local dev entry point
├── README.md                     # User-facing documentation
├── LOG_EVENTS_REMOVAL_REVIEW.md  # Event logging decisions
└── claude.md                     # This file
```

---

## How Claude Should Approach Catalitium

### Guiding Principles

1. **Respect the Mission**: Every change should serve tech talent—not clutter, not complexity
2. **Simplicity First**: Prefer Flask templates over JavaScript frameworks; CSV over complex databases
3. **Quality Over Features**: One polished feature beats five half-baked ones
4. **Data Privacy**: Minimal collection; be transparent about tracking
5. **Search-First Mindset**: UX decisions center on finding jobs, not scrolling

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
- Event tracking accuracy (GTM integration)

**Performance & Reliability**
- Query optimization (SQLite indexing)
- CSV data pipeline improvements
- Job import/sync automation
- Caching strategies for salary data

**Testing & Quality**
- Unit tests for search logic, salary enrichment, filtering
- Integration tests for job search flows
- UI testing for subscription modals, pagination
- GTM event verification

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
| `app/app.py` | Flask app factory; routes for search, job detail, subscriptions |
| `app/search.py` | Smart search engine; handles fuzzy matching, filtering, synonyms |
| `app/salary_utils.py` | Salary lookup, delta calculations, market insights |
| `app/models.py` | Data structures (Job, Salary, Subscriber) |
| `app/db.py` | SQLite operations (subscriptions, search logs) |
| `jobs.csv` | Job listings (source of truth) |
| `salary.csv` | Salary reference data by city/country |

---

## Development Workflow

### Local Setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

### Running Tests
```bash
pytest  # If test suite exists; add if not present
```

### Data Updates
- **Jobs**: Update `jobs.csv` directly
- **Salary**: Update `salary.csv` (city, country, salary columns required)
- **Restart**: No restart needed; CSV is read on each request

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
- GTM events fire correctly for analytics

✅ **User Experience**
- Job search is intuitive (minimal clicks to find matches)
- Mobile works seamlessly
- Subscription signup is friction-free
- Error messages are helpful, not scary

✅ **Reliability**
- CSV imports don't break existing data
- Subscriptions are reliable (no lost emails)
- No data loss during deployments
- Search works offline-first (no external API dependency)

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
1. Update CSV data to include new field
2. Add filter UI in `templates/index.html`
3. Implement filter logic in `app/search.py`
4. Add tests for edge cases
5. Update GTM to track new filter usage

### Adding a New Data Source
1. Create a new CSV (e.g., `salaries_2024.csv`)
2. Add loader in `app/models.py`
3. Merge data with existing salary lookup in `app/salary_utils.py`
4. Test fallback behavior if new source is incomplete

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

*Last updated: February 2025*
*This document is the source of truth for Catalitium's vision and technical direction.*
