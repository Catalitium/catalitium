# PLAN — Career Decision Intelligence Tools

**Branch:** `feature/career-decision-intelligence`
**Sprint:** 2 — Levels.fyi Feature Sprint
**Prefix:** `/career/` routes, `career_*` functions

---

## Objective

Build six career decision-intelligence tools that help professionals evaluate job offers, understand AI exposure, track hiring velocity, estimate earnings, explore career paths, and benchmark their market position. All read-only against existing schema — no new tables, no new dependencies.

## Deliverables

### A. Model Layer — `app/models/career.py`

| Function | Purpose |
|----------|---------|
| `compute_worth_it_score(job_dict, salary_ref, company_stats)` | Score a job 0-100 across 5 dimensions (salary, company signal, role quality, remote, alternatives) |
| `find_alternatives(title, location, exclude_id, limit)` | Search for similar jobs excluding current one |
| `compute_ai_exposure(function_category)` | Rank function categories by % of AI-mentioning job descriptions |
| `get_hiring_velocity(location, function, limit)` | Compare company hiring last 30 days vs previous 30 days |
| `estimate_earnings(title, location, currency)` | Build low/median/high salary range from reference + submissions |
| `get_career_paths(title_norm)` | Derive progression, lateral moves, top employers from jobs table |
| `compute_market_position(title, location, years_exp, current_salary, currency)` | Return percentile rank vs market |

### B–G. Routes & Templates

| Route | Template | Description |
|-------|----------|-------------|
| `GET /career/evaluate` | `career_evaluate.html` | "Is This Worth It?" score breakdown with gauge |
| `GET /career/ai-exposure` | `career_ai_exposure.html` | AI exposure ranking by function category |
| `GET /career/hiring-trends` | `career_hiring_trends.html` | Hiring velocity dashboard (hot/cooling/stable) |
| `GET /career/earnings` | `career_earnings.html` | First-year earnings estimator with visual bar |
| `GET /career/paths` | `career_paths.html` | Career path explorer (next steps, lateral, employers) |
| `GET /career/market-position` | `career_market_position.html` | Market position tool with percentile gauge |

### H. Integration

- `job_detail.html`: Add "Is this role worth it?" link near salary area
- `compare.html`: Add "Evaluate" link per job in the comparison table
- Sitemap: 6 new career URLs at priority 0.7

### I. Tests — `tests/test_career.py`

- Unit tests for each model function (structure, edge cases)
- Route smoke tests (200 status)
- ≥20 tests total

## Architecture Decisions

- **Read-only queries** on `jobs`, `salary`, `salary_submissions` tables
- **Conservative fallbacks** via try/except — graceful degradation when DB unavailable
- All templates extend `base.html`, use existing Tailwind CDN classes
- `noindex` on ephemeral evaluation pages, proper SEO on reference pages

## Files Touched

| File | Action |
|------|--------|
| `app/models/career.py` | CREATE |
| `app/views/templates/career_*.html` (×6) | CREATE |
| `tests/test_career.py` | CREATE |
| `app/app.py` | ADD routes + sitemap entries |
| `app/views/templates/job_detail.html` | ADD "worth it" link |
| `app/views/templates/compare.html` | ADD evaluate link |
| `PLAN.md` | CREATE |
| `HANDOFF.md` | CREATE |

## Out of Scope

- Carl integration
- New Python dependencies
- New database tables or migrations
- Modifications to base.html, index.html, job_card.html, main.js, companies.html, salary_report.html

---

*Created: April 2026*
