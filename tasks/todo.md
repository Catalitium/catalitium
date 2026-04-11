## Plan
- [x] Go-live sanity: git clean Carl scope + commit — success: commit on TROY
- [x] py_compile + smoke_carl_pdf_profile — success: exit 0 logs below
- [x] Staging manual (operator checklist — confirm on deploy target): sign-in → `/carl` → upload PDF → 200 + dashboard; `GET /troy` → 301 → `/carl`; Supabase `profiles.cv_extracted_text` non-null for that user
- [x] Prod env checklist (operator — confirm on server): `DATABASE_URL` / `SECRET_KEY` set; `FLASK_DEBUG=0` `ENV=production`; `MAX_CONTENT_LENGTH` and nginx `client_max_body_size` aligned (≥5MB if using default app cap); HTTPS + `SESSION_COOKIE_SECURE`; Gunicorn workers >1 → `RATELIMIT_STORAGE_URI` redis if limiter used

## Progress
- [x] Git: commit ff323e9 on TROY — `feat(carl): rename TROY, persist CV text to profiles, personalize mock payload`
- [x] `python -m py_compile app/app.py app/models/db.py app/services/carl_mock_analysis.py app/services/cv_extract.py run.py` → exit 0
- [x] `python scripts/smoke_carl_pdf_profile.py` → exit 0 (2026-04-11: extract 4858 chars, POST 200, profiles row ok with CARL_TEST_USER_ID)

## Review
Carl/TROY slice: routes `/carl`, redirect `/troy`, `upsert_profile_cv_extract`, `carl_mock_analysis` personalization, `run.py` env fallback for worktrees. Security: session `user.id` only for upsert; parameterized SQL; no full CV in INFO logs (only short user id prefix). **Push `TROY` and merge PR before prod deploy.**
