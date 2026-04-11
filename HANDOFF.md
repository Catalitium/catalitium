# HANDOFF — Smart Discovery & Explore Hub

**Branch:** `feature/smart-discovery-explore`
**Sprint:** 2 — Levels.fyi Feature Sprint
**Status:** Complete — 34/34 tests passing

---

## What Was Built

### A) `app/models/explore.py` (NEW)
- `compute_quality_score(job_dict)` → QualityScore dict per AGENT_CONTRACT.md
- `categorize_function(title_norm)` → maps title keywords to 10 categories + Other
- `get_explore_data()` → top 20 titles, locations, companies with job counts
- `get_remote_companies(limit=50)` → companies ranked by remote job %
- `get_function_distribution(location=None)` → job counts per function category
- `get_hiring_urgency(company_name)` → True if 5+ jobs in last 14 days

### B) Explore Hub — `GET /explore`
- Three-panel tile layout: top titles, top locations, top companies
- Each tile links to pre-filtered `/jobs` search
- JSON-LD ItemList for SEO

### C) Advanced Filter Panel on `/jobs`
- Collapsible "Advanced Filters" section below main search form
- Filters: remote-only (checkbox), has salary (checkbox), freshness (7/14/30/all), function chips (8 categories), salary max (number input)
- All passed as GET params to existing `/jobs` route
- `Job._where()` extended with `remote`, `has_salary`, `freshness`, `function_cat`, `salary_max` keyword arguments
- `Job.count()` and `Job.search()` accept and forward `**filter_kw`

### D) Quality Score on Job Cards
- Computed per row in `jobs()` route via `compute_quality_score(row)`
- Displayed as colored dot (green >= 70, amber >= 40, gray < 40) with "Quality: X/100" tooltip
- Added to `job_card.html` metadata area

### E) Remote-Friendliness — `GET /explore/remote-companies`
- Company cards with: name, remote %, total jobs, remote count, progress bar
- Sorted by remote % descending, then total jobs

### F) Function Browse — `GET /explore/functions`
- Grid of function category cards with job count, salary data %
- Each links to `/jobs?function=<category>`
- Category-specific icons and colors

### G) Route Wiring
- Three new routes in `app.py`: `explore_hub`, `explore_remote`, `explore_functions`
- All added to sitemap with priority 0.7
- Import from `app.models.explore`

### H) Filter localStorage Persistence
- `main.js` saves advanced filter selections to `catalitium_adv_filters` in localStorage
- Restores on next visit when no URL params present

---

## Files Changed

| File | Action |
|------|--------|
| `PLAN.md` | Created |
| `HANDOFF.md` | Created |
| `app/models/explore.py` | Created (new module) |
| `app/models/jobs.py` | Extended `_where()`, `count()`, `search()` signatures |
| `app/app.py` | Added explore import, 3 routes, quality score in jobs(), advanced filter parsing, sitemap entries |
| `app/views/templates/explore.html` | Created |
| `app/views/templates/explore_remote.html` | Created |
| `app/views/templates/explore_functions.html` | Created |
| `app/views/templates/index.html` | Added collapsible advanced filter panel |
| `app/views/templates/components/job_card.html` | Added quality score badge |
| `app/static/js/main.js` | Added filter localStorage persistence |
| `tests/test_explore.py` | Created (34 tests) |

---

## Test Results

```
34 passed, 25 warnings in 245.61s
```

All warnings are deprecation notices from `supabase` and `psycopg_pool` — not related to this branch.

---

## Merge Notes

- Follows AGENT_CONTRACT.md file-touch rules strictly
- Does NOT touch: `base.html`, `salary_report.html`, `compare.html`, `companies.html`, `company_detail.html`, `compensation_methodology.html`
- No new Python dependencies
- No new database tables (all read-only queries)
- Route prefix: `/explore/`
- Function prefix: `explore_*`

---

*Completed: April 2026*
