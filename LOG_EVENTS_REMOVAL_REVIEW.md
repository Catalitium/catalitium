# log_events Removal — Review Report

**Date:** 2025-02-08  
**Status:** PASS — Safe to drop `log_events` table

---

## 1. Code references

| Check | Result |
|-------|--------|
| `log_events` (table name) | **0 matches** |
| `log_event` (function) | **0 matches** |
| `insert_search_event` | **0 matches** |
| `insert_subscribe_event` | **0 matches** |

**Conclusion:** No code references the `log_events` table or the removed logging functions.

---

## 2. Database INSERT operations

All INSERT usage in the app was checked:

| File | Line | Table | Safe? |
|------|------|--------|-------|
| `app/models/db.py` | 188 | `subscribers` | Yes |
| `app/models/db.py` | 208 | `contact_form` | Yes |
| `app/models/db.py` | 232 | `job_posting` | Yes |
| `app/models/db.py` | 690, 759 | `jobs` | Yes |

**Conclusion:** No INSERT targets `log_events`. Only `subscribers`, `contact_form`, `job_posting`, and `jobs` are written to.

---

## 3. Imports in `app/app.py`

Current imports from `app.models.db`:

- `insert_subscriber`
- `insert_contact`
- `insert_job_posting`
- `Job`
- (plus parsing/formatting helpers)

**Conclusion:** No `log_event`, `insert_search_event`, or `insert_subscribe_event` are imported or used.

---

## 4. `/events/apply` endpoint

- **Route:** `POST /events/apply` (lines 858–907 in `app/app.py`)
- **Behavior:** Parses JSON payload, normalizes fields, then returns `{"status": "ok"}` with status 200.
- **Database:** No `get_db()`, no `cur.execute`, no write to any table.

**Conclusion:** This endpoint does not touch the database. Safe with respect to `log_events`.

---

## 5. Tests

Searched `tests/` for `log_events` and `log_event`: **0 matches**.

**Conclusion:** No tests depend on `log_events` or the old logging API.

---

## 6. Verdict

- No code reads or writes the `log_events` table.
- No remaining references to the removed logging functions or the table name.
- **You can safely drop the `log_events` table** in your backend database.

---

## 7. Recommended SQL

Run this against your Postgres (or equivalent) database:

```sql
DROP TABLE IF EXISTS log_events;
```

After dropping, sanity-check the app (e.g. hit main pages and `/events/apply`) and check logs for any new DB errors.
