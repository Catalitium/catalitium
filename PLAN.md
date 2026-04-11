# Plan: Company Intelligence Pages

**Branch:** `feature/company-intelligence-pages`
**Scope:** Turn static mock `/companies` into DB-driven company discovery hub + individual company profiles.
**Constraint:** Read-only queries on existing `jobs` table. No new tables, no new Python deps.

---

## Architecture

### Data Source
All company data is aggregated from the `jobs` table via `GROUP BY company_name`.
Companies must have **>= 2 jobs** to appear (filters out noise/one-off postings).

### Type Shape (from AGENT_CONTRACT.md)
```python
CompanyAggregate = {
    "slug": str,                  # url-safe slugified company_name
    "name": str,                  # original company_name
    "job_count": int,
    "locations": list[str],       # distinct country values
    "titles_normalized": list[str],
    "has_salary_data": bool,
    "latest_posting_date": str,   # ISO date string or ""
    "salary_range_display": str | None,
}
```

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `app/models/jobs.py` | EDIT | Add `company_list()`, `company_detail()`, `company_count()` static methods |
| `app/app.py` | EDIT | Rewrite `companies()` route, add `company_detail_page()` route, update `job_detail()` to pass `company_slug`, add companies to sitemap |
| `app/views/templates/companies.html` | REWRITE | DB-driven company listing with search, pagination, cards |
| `app/views/templates/company_detail.html` | NEW | Individual company profile page |
| `app/views/templates/job_detail.html` | EDIT | Make company name a link to `/companies/<slug>` |
| `tests/test_companies.py` | NEW | Unit + route tests for company features |

### Files NOT Touched
- `app/static/js/main.js`
- `app/views/templates/components/job_card.html`
- `app/views/templates/base.html`
- `requirements.txt`
- Any salary section in `job_detail.html`

---

## Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| GET | `/companies` | `companies()` | Company listing with search + pagination |
| GET | `/companies/<slug>` | `company_detail_page()` | Individual company profile |

---

## SQL Queries

### company_list
```sql
SELECT company_name, COUNT(*) as job_count,
       array_agg(DISTINCT country) as countries,
       MAX(date) as latest_date,
       COUNT(CASE WHEN salary IS NOT NULL AND salary != '' THEN 1 END) as salary_count
FROM jobs
GROUP BY company_name
HAVING COUNT(*) >= 2
ORDER BY COUNT(*) DESC
LIMIT %s OFFSET %s
```

### company_count
```sql
SELECT COUNT(*) FROM (
    SELECT company_name FROM jobs GROUP BY company_name HAVING COUNT(*) >= 2
) sub
```

### company_detail
Aggregated stats for one company: job_count, locations, title distribution, salary %, latest date.
Plus job listing via existing `Job.search`-like pattern filtered by `company_name`.

---

## Implementation Order
1. `app/models/jobs.py` — aggregation helpers
2. `app/app.py` — routes
3. `app/views/templates/companies.html` — listing page
4. `app/views/templates/company_detail.html` — detail page
5. `app/views/templates/job_detail.html` — company link
6. `app/app.py` — sitemap entries
7. `tests/test_companies.py` — tests
8. Run pytest, fix issues
9. HANDOFF.md + commit
