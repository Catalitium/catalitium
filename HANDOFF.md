# HANDOFF — Salary Intelligence Hub

**Branch:** `feature/salary-intelligence-hub`
**Sprint:** 2

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `PLAN.md` | CREATED | Sprint plan |
| `HANDOFF.md` | CREATED | This file |
| `app/models/salary_analytics.py` | CREATED | Analytics engine: percentile, PPP, function benchmarks, trends |
| `app/views/templates/salary_underpaid.html` | CREATED | "Am I Underpaid?" percentile checker |
| `app/views/templates/salary_compare_cities.html` | CREATED | Cross-city PPP salary comparison |
| `app/views/templates/salary_by_function.html` | CREATED | Function/team salary benchmarks |
| `app/views/templates/salary_trends.html` | CREATED | Monthly salary trend data |
| `app/app.py` | MODIFIED | Added 4 routes, import, 4 sitemap entries |
| `app/views/templates/salary_report.html` | MODIFIED | Added "Salary Intelligence" cross-link section |
| `tests/test_salary_analytics.py` | CREATED | 34 tests (unit + route smoke) |

## Routes Added

| URL | Function | Method | Description |
|-----|----------|--------|-------------|
| `/salary/am-i-underpaid` | `salary_underpaid` | GET | Percentile calculator form + results |
| `/salary/compare-cities` | `salary_compare_cities` | GET | Cross-city PPP comparison |
| `/salary/by-function` | `salary_by_function` | GET | Salary by function/team category |
| `/salary/trends` | `salary_trends` | GET | Monthly salary trend data |

## Test Results

```
34 passed, 12 warnings in 117.50s
```

All 34 tests pass. Warnings are pre-existing (psycopg_pool deprecation, supabase gotrue deprecation).

### Test Breakdown
- 5 tests: PPP indices completeness and correctness
- 15 tests: categorize_function with parametrized title keywords
- 6 tests: compute_percentile shape, clamping, labels
- 3 tests: compare_cities_salary structure
- 6 tests: Route smoke tests (all 4 routes return 200)

## Known Issues

1. **DB-dependent functions return empty results in test env**: `get_function_benchmarks` and `get_salary_trends` require a live database with `job_salary` data to return meaningful results. They gracefully return empty lists when DB is unavailable.
2. **PPP indices are hardcoded**: The 31-city PPP index is static. Future work could pull from an external API or allow admin updates.
3. **Percentile is approximate**: Uses `user_salary / median * 50` rather than a true statistical percentile from the full distribution. This is by design (documented in methodology section).
4. **Currency conversion not applied**: Raw comparisons assume same currency context. Cross-currency normalization is not in scope for this sprint.

## Merge Notes

- **No conflicts expected** with other Sprint 2 branches (`smart-discovery-explore`, `career-decision-intelligence`) per AGENT_CONTRACT.md file-touch rules.
- Only shared file modified: `app/app.py` — routes use unique `salary_*` prefix and `/salary/` URL prefix.
- `salary_report.html` is exclusively owned by this branch per contract.
- No new Python dependencies added.
- No new database tables or migrations.
- All templates extend `base.html` without modifying it.
