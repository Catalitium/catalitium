# Catalitium — Task Plan

## Plan

- [x] Task 1: Fix DB query timeout — raised statement_timeout 800ms → 8000ms
- [x] Task 2: Fix blank SECRET_KEY — generated 64-char hex key, loaded OK
- [x] Task 3: Verify subscribe POST → Supabase — POST returned `{"status":"ok"}` HTTP 200, no errors

## Progress

- [x] Task 1 — `GET /` returns HTTP 200 in 2s, zero QueryCanceled errors
- [x] Task 2 — `SECRET_KEY` is 64 chars, loads cleanly from .env
- [x] Task 3 — `POST /subscribe.json` → `{"status":"ok"}` HTTP 200, row written to Supabase `subscribers` table

## Review

All 3 tasks green. App boots cleanly, DB writes work, SECRET_KEY secured.

**Open questions for next session:**
- [x] `subscribers` has `UNIQUE INDEX` on email — duplicate detection works
- [x] `search_title` + `search_country` now saved on every subscription
- [x] SMTP configured — Gmail smtp.gmail.com:587, app password set, 8/8 smoke test passed
- [ ] `jobs` table has 85,316 rows confirmed in Supabase
