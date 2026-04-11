## Plan
- [x] Go-live sanity: git clean Carl scope + commit — success: commit on TROY
- [x] py_compile + smoke_carl_pdf_profile — success: exit 0 logs below
- [ ] Staging manual (operator): sign-in /carl upload, /troy 301, Supabase profiles — human verify before prod
- [ ] Prod env checklist (operator): DATABASE_URL, SECRET_KEY, MAX_CONTENT_LENGTH, HTTPS, Gunicorn + limiter

## Progress
- [x] Git: staged Carl rename + profiles CV upsert + smoke script (proof: `git log -1 --oneline`)
- [x] `python -m py_compile app/app.py app/models/db.py app/services/carl_mock_analysis.py app/services/cv_extract.py run.py` → exit 0
- [x] `python scripts/smoke_carl_pdf_profile.py` → exit 0 (extract + POST /carl/analyze 200; DB row if CARL_TEST_USER_ID set)

## Review
Carl/TROY slice: routes `/carl`, redirect `/troy`, `upsert_profile_cv_extract`, `carl_mock_analysis` personalization, `run.py` env fallback for worktrees. Staging/prod items require deploy target confirmation.
