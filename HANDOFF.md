# Handoff: Company Intelligence Pages

**Branch:** `feature/company-intelligence-pages`
**Date:** 2026-04-11

---

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `PLAN.md` | NEW | Architecture plan for the feature |
| `HANDOFF.md` | NEW | This file |
| `app/models/jobs.py` | EDITED | Added `company_list()`, `company_count()`, `company_detail()`, `company_jobs()`, `company_name_by_slug()` static methods on `Job` class |
| `app/app.py` | EDITED | Rewrote `companies()` route (DB-driven with search + pagination), added `company_detail_page()` route at `/companies/<slug>`, added `company_slug` to `job_detail` context, added top 50 company pages to sitemap, bumped `/companies` sitemap priority to 0.8 |
| `app/views/templates/companies.html` | REWRITTEN | DB-driven company listing with search input, card grid, pagination, empty state, SEO meta |
| `app/views/templates/company_detail.html` | NEW | Individual company profile page with stats, title distribution, job listings, breadcrumbs, JSON-LD Organization schema |
| `app/views/templates/job_detail.html` | EDITED | Company name is now a link to `/companies/<slug>` (only the `<p>` tag wrapping company name, salary section untouched) |
| `tests/test_companies.py` | NEW | 13 tests covering model helpers and routes |

---

## Routes Added

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| GET | `/companies` | `companies()` | Company discovery hub (rewritten from static mock) |
| GET | `/companies/<slug>` | `company_detail_page()` | Individual company profile |

---

## Test Results

```
tests/test_companies.py: 13 passed, 0 failed
```

All 13 company tests pass:
- `test_company_list_returns_list` — model shape validation
- `test_company_list_with_search` — ILIKE search filter
- `test_company_list_handles_db_error` — graceful fallback
- `test_company_count_returns_int` — count query
- `test_company_count_handles_db_error` — graceful fallback
- `test_company_detail_returns_dict` — detail shape
- `test_company_detail_returns_none_for_empty` — not found case
- `test_company_detail_empty_name` — guard clause
- `test_companies_route_200` — listing page renders
- `test_companies_route_with_search` — search param works
- `test_companies_route_with_data` — renders company cards
- `test_company_detail_route_404_unknown` — unknown slug returns 404
- `test_company_detail_route_200` — full mock renders profile

Pre-existing test `test_http_health_ok` fails due to DB connectivity (not related to this branch).

---

## Known Issues

1. **Slug collision risk**: If two different companies slugify to the same value, only the first match is returned. This is unlikely with real company names but possible for very short names. A future fix could add a slug column or use a deterministic tiebreaker.

2. **Performance at scale**: `company_name_by_slug()` scans all companies with >= 2 jobs and compares slugs in Python. For large datasets (10k+ companies), consider adding a materialized view or caching slug→name mappings.

3. **No company logos/descriptions**: Cards show the first letter of the company name as a placeholder. Logos would require a separate data source.

---

## Merge Notes

- This branch touches `app/app.py` (adds routes in the companies section + sitemap update + minor edit in job_detail render call). Check for conflicts with `feature/compensation-intelligence` and `feature/candidate-decision-tools` per AGENT_CONTRACT.md.
- The `job_detail.html` edit is minimal (only the company name `<p>` tag, not the salary section), so conflicts with compensation branch should be low.
- `app/models/jobs.py` only has additions (new static methods at the end of the class), no modifications to existing methods.
- `components/job_card.html` was NOT touched per contract rules.
