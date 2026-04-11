# Plan: Candidate Decision Tools

**Branch:** `feature/candidate-decision-tools`
**Agent contract:** AGENT_CONTRACT.md (shared types, file-touch rules)
**Scope:** Side-by-side job comparison tool + wire orphaned tracker page

---

## Architecture

All scoring logic is pure Python (no DB writes, no new tables).
Compare workspace fetches jobs via `Job.get_by_id`, enriches with salary data
using the same pattern as `job_detail`, and scores each with a deterministic
scoring engine. The compare selection state lives in `localStorage`
(`catalitium_compare`, max 4 items). The orphaned `tracker.html` gets a simple
GET route.

## Deliverables & Files

| # | Deliverable | File(s) | Action |
|---|-------------|---------|--------|
| A | Compare scoring engine | `app/models/compare.py` | **NEW** |
| B | Compare workspace page | `app/app.py`, `app/views/templates/compare.html` | ADD route, **NEW** template |
| C | Compare button on cards | `app/views/templates/components/job_card.html` | EDIT (actions row) |
| D | Compare localStorage + nav badge | `app/static/js/main.js` | EDIT (append section) |
| E | Wire tracker route + sitemap | `app/app.py` | ADD route, EDIT sitemap |
| F | Tests | `tests/test_compare.py` | **NEW** |

## Data Flow

```
[Search page] → user clicks Compare btn → localStorage catalitium_compare (max 4)
             → "Compare now" floating btn → /compare?ids=1,2,3
             → Flask route fetches jobs, enriches salary, calls score_job()
             → compare.html renders side-by-side grid with score bars
```

## Scoring Weights (score_job)

| Factor | Weight | Condition |
|--------|--------|-----------|
| salary_present | 25 | job has non-empty salary text |
| salary_confidence | 20 | estimated salary range available via location lookup |
| freshness | 20 | posted within last 14 days |
| remote | 15 | location contains "remote" (case-insensitive) |
| description_quality | 20 | description length > 200 chars |

Total: 0–100. Deterministic, no randomness.

## Constraints

- No new Python dependencies
- No new database tables; read-only queries
- No modifications to `companies.html` or `job_detail.html` salary section
- No modifications to `base.html`
- Carl is out of scope

---

*Created: April 2026*
