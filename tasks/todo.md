# Catalitium — Task Backlog

> Local-only file. Not committed. See claude-rules.md for workflow.

## Active Sprint: LHF Sprint 001
- [ ] Verify salary table indexes applied via `init_db()`
- [ ] Confirm `GET /jobs?salary_min=100000` returns filtered results
- [ ] Check chat-widget.js absent from /about, /legal, /salary-tools page source
- [ ] Confirm view toggle + salary explorer state survive reload
- [ ] Run accessibility audit on footer SVGs

## Backlog (S1–S10 simplifications)
- [ ] S1: Unify salary formatting — Python Jinja filter, remove JS duplicate
- [ ] S2: Extract shared `formatCurrency()` to `utils.js`
- [ ] S3: Consolidate job card rendering (job_browser.js vs components/job_card.html)
- [ ] S4: Load COUNTRY_NORM from country_norm.json
- [ ] S5: Split main.js into subscribe.js, nav.js, dialog.js
- [ ] S6: Ghost job threshold → named constant (currently magic number 30)
- [ ] S7: Add Jinja `truncate_text` filter
- [ ] S8: Add `title` attribute to truncated job descriptions
- [ ] S9: Replace hardcoded demo jobs with demo_jobs.csv
- [ ] S10: Add pytest + 3 smoke tests
