# Compensation Intelligence — Handoff

**Branch:** `feature/compensation-intelligence`
**Status:** Complete, ready for merge

---

## Files Changed

### New files
| File | Purpose |
|------|---------|
| `app/models/compensation.py` | Confidence scoring engine (`compute_compensation_confidence`, `confidence_color`, `source_label`) |
| `app/views/templates/compensation_methodology.html` | Static methodology page explaining estimation approach |
| `tests/test_compensation.py` | 22 tests covering scoring, labels, colors, and route |
| `PLAN.md` | Architecture plan |
| `HANDOFF.md` | This file |

### Modified files
| File | Change |
|------|--------|
| `app/app.py` | Import compensation module; wire into `job_detail` and `jobs` routes; add `compensation_methodology` route; add to sitemap |
| `app/views/templates/job_detail.html` | Confidence badge (green/amber/gray) + source provenance label + "How we estimate this" link in salary section |
| `app/views/templates/components/job_card.html` | Small confidence percentage indicator next to estimated salary badge |

## Routes Added

| Path | Function | Method | Description |
|------|----------|--------|-------------|
| `/compensation/methodology` | `compensation_methodology` | GET | Static page explaining salary estimation methodology |

## Test Results

```
22 passed, 0 failed
```

### Test coverage
- `TestConfidenceScoring` (11 tests): employer salary, city/country/fallback reference levels, crowd data, no data, combined signals, clamping, methodology URL
- `TestSourceLabel` (5 tests): all source types + unknown fallback
- `TestConfidenceColor` (3 tests): green/amber/gray thresholds
- `TestMethodologyRoute` (3 tests): 200 status, title present, confidence explanation present

## Known Issues

- `ref_match_level` is heuristically set to `"city"` when salary reference data exists; the existing `get_salary_for_location` function doesn't expose which tier matched (city vs region vs country). A future enhancement could have `get_salary_for_location` return the match tier for more precise confidence scoring.
- `has_crowd_data` is always `False` in the current wiring — querying `salary_submissions` per job would add latency. This can be enabled later with a batch query approach.
- Pre-existing test `test_http_health_ok` fails independently of this branch (DB health check issue). Pre-existing `test_http_security_headers_on_homepage` hangs due to connection pool timeout — unrelated to compensation changes.

## Merge Notes

- **Conflict zones per AGENT_CONTRACT.md**: `job_card.html` is the primary conflict zone (both compensation and candidate-decision-tools branches add to card actions area). The compensation badge is added next to the salary badge in the meta badges area, while the candidate branch adds a compare button in the actions area — these should merge cleanly.
- **app.py**: The compensation route block is inserted before the salary tools section. Import is added at the top-level imports. Both are in distinct sections from other branches.
- **No new dependencies, no new tables, no migrations.**
- **Template changes**: All new templates extend `base.html`. No changes to `base.html` itself.

---

*Completed: April 2026 | Sprint: Three-Worktree Overnight*
