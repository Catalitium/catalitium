## Plan
- [x] Go-live sanity: git clean Carl scope + commit — success: commit on TROY
- [x] py_compile + smoke_carl_pdf_profile — success: exit 0 logs below
- [ ] Staging manual (operator): sign-in /carl upload, /troy 301, Supabase profiles — human verify before prod
- [ ] Prod env checklist (operator): DATABASE_URL, SECRET_KEY, MAX_CONTENT_LENGTH, HTTPS, Gunicorn + limiter

## Progress
- [x] Git: commit ff323e9 on TROY — `feat(carl): rename TROY, persist CV text to profiles, personalize mock payload`
- [x] `python -m py_compile app/app.py app/models/db.py app/services/carl_mock_analysis.py app/services/cv_extract.py run.py` → exit 0
- [x] `python scripts/smoke_carl_pdf_profile.py` → exit 0 (2026-04-11: extract 4858 chars, POST 200, profiles row ok with CARL_TEST_USER_ID)

## Review
Carl/TROY slice: routes `/carl`, redirect `/troy`, `upsert_profile_cv_extract`, `carl_mock_analysis` personalization, `run.py` env fallback for worktrees. Staging/prod items require deploy target confirmation.
