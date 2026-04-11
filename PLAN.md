# PLAN — Salary Intelligence Hub

**Branch:** `feature/salary-intelligence-hub`
**Sprint:** 2
**Agent Contract Shape:** `SalaryPercentile`

---

## Goal

Transform raw salary data into actionable analytics via four new pages under `/salary/`. No new DB tables, no new Python deps. Read-only queries on `jobs`, `salary`, `salary_submissions`.

## Deliverables

### A) `app/models/salary_analytics.py` — Analytics Engine
- `compute_percentile(title, location, user_salary, currency)` → SalaryPercentile dict
- `get_ppp_indices()` → hardcoded PPP index for ~30 tech cities
- `compare_cities_salary(title, cities)` → raw + PPP-adjusted comparison
- `categorize_function(title_norm)` → function category string
- `get_function_benchmarks(location)` → aggregated salary by function
- `get_salary_trends(title_category, city, months)` → monthly median + count

### B) `/salary/am-i-underpaid` — Percentile Checker
- Form: title, location, salary, currency
- Visual gauge (Tailwind), market label, methodology link
- Template: `salary_underpaid.html`

### C) `/salary/compare-cities` — Cross-City Comparison
- Form: title + up to 4 cities
- Side-by-side cards: raw median vs PPP-adjusted
- Bar chart via Tailwind progress bars
- Template: `salary_compare_cities.html`

### D) `/salary/by-function` — Function Benchmarks
- Salary medians by category (Backend, Frontend, ML/AI, etc.)
- Optional location filter
- Links to filtered job search
- Template: `salary_by_function.html`

### E) `/salary/trends` — Salary Trends
- Monthly aggregates of job_salary from jobs table
- Filter by title category or city
- Interpretation text
- Template: `salary_trends.html`

### F) Route Wiring in `app/app.py`
- 4 new routes with `salary_*` function names
- Sitemap entries at priority 0.7
- Cross-links added to `salary_report.html`

### G) Tests in `tests/test_salary_analytics.py`
- Unit tests for all analytics functions
- Route smoke tests (200 status)
- 15+ tests minimum

## File Touch Plan

| File | Action |
|------|--------|
| `app/models/salary_analytics.py` | CREATE |
| `app/views/templates/salary_underpaid.html` | CREATE |
| `app/views/templates/salary_compare_cities.html` | CREATE |
| `app/views/templates/salary_by_function.html` | CREATE |
| `app/views/templates/salary_trends.html` | CREATE |
| `app/app.py` | ADD routes (salary_ prefix) |
| `app/views/templates/salary_report.html` | ADD cross-links section |
| `tests/test_salary_analytics.py` | CREATE |
| `PLAN.md` | CREATE |
| `HANDOFF.md` | CREATE |

## Constraints
- No touch: index.html, job_card.html, main.js, companies.html, compare.html, job_detail.html, base.html
- No new Python deps
- No new DB tables
- Read-only DB queries
- All templates extend base.html
- Tailwind CDN classes only
