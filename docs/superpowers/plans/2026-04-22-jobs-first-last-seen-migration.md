# Jobs First/Last Seen Schema Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `first_seen_at` and `last_seen_at` tracking to the `jobs` table so repeated crawls can update listing recency without duplicating rows.

**Architecture:** Use a two-phase rollout. Phase 1 adds nullable columns and backfills safely. Phase 2 updates the ingest upsert path from `ON CONFLICT DO NOTHING` to `ON CONFLICT DO UPDATE SET last_seen_at = NOW()` while preserving existing insert behavior for new rows.

**Tech Stack:** PostgreSQL (Supabase), Flask + psycopg SQL execution, existing `app/models/catalog.py` ingest path.

---

## Scope And Constraints

- In scope:
  - `jobs.first_seen_at` (`TIMESTAMPTZ`)
  - `jobs.last_seen_at` (`TIMESTAMPTZ`)
  - Ingest upsert behavior for duplicate `link` rows
  - Operational validation and rollback playbook
- Out of scope:
  - New endpoints, new pages, analytics rebuilds, CARL B2B scoring logic changes
  - Any schema rewrite beyond the two new timestamp columns

---

## Current Baseline (Verified)

- Job ingestion currently inserts into `jobs` with:
  - `ON CONFLICT (link) DO NOTHING`
- Relevant insertion code lives in:
  - `app/models/catalog.py` (`Job.insert_many`)
- Existing startup schema bootstrap is centralized in:
  - `app/models/db.py` (`init_db`)

Implication: repeated sightings of the same listing are ignored, so there is no durable "last observed" timestamp.

---

## Target Data Contract

- `first_seen_at`: first time this `link` was observed by Catalitium.
  - Set once on insert.
  - Never overwritten on conflict updates.
- `last_seen_at`: most recent time this `link` was observed.
  - Set on insert.
  - Updated on every conflict hit for the same `link`.

Recommended invariants:

- `first_seen_at IS NOT NULL`
- `last_seen_at IS NOT NULL`
- `last_seen_at >= first_seen_at`

---

## Rollout Strategy

### Phase 1 - Additive Schema Change

Add columns nullable first to avoid lock-heavy table rewrites:

```sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
```

Backfill in one pass (safe default: reuse existing `date` when available, otherwise `NOW()`):

```sql
UPDATE jobs
SET
  first_seen_at = COALESCE(first_seen_at, date::timestamptz, NOW()),
  last_seen_at  = COALESCE(last_seen_at,  date::timestamptz, NOW())
WHERE first_seen_at IS NULL OR last_seen_at IS NULL;
```

Then enforce constraints:

```sql
ALTER TABLE jobs
  ALTER COLUMN first_seen_at SET NOT NULL,
  ALTER COLUMN last_seen_at SET NOT NULL;

ALTER TABLE jobs
  ADD CONSTRAINT jobs_seen_window_chk
  CHECK (last_seen_at >= first_seen_at);
```

### Phase 2 - Ingest Upsert Cutover

Change conflict behavior in `Job.insert_many`:

- Before:
  - `ON CONFLICT (link) DO NOTHING`
- After:
  - `ON CONFLICT (link) DO UPDATE SET last_seen_at = NOW()`

Insert path requirements:

- New rows:
  - write `first_seen_at = NOW()`
  - write `last_seen_at = NOW()`
- Existing rows (conflict):
  - keep `first_seen_at` unchanged
  - refresh `last_seen_at`

Recommended conflict clause:

```sql
ON CONFLICT (link) DO UPDATE
SET last_seen_at = NOW()
```

Note: keep update narrow to avoid unnecessary write amplification.

---

## Implementation Task List

### Task 1: Prepare migration SQL and prechecks

**Files:**
- Create: `scripts/sql/migrations/2026-04-22_jobs_seen_timestamps_up.sql`
- Create: `scripts/sql/migrations/2026-04-22_jobs_seen_timestamps_down.sql`
- Optional docs note: `README.md` migration section (if team prefers documenting manual migration runs)

- [ ] **Step 1: Capture baseline row quality**

Run:

```sql
SELECT
  COUNT(*) AS total_rows,
  COUNT(*) FILTER (WHERE link IS NULL OR link = '') AS empty_link_rows,
  COUNT(*) FILTER (WHERE date IS NULL) AS null_date_rows
FROM jobs;
```

Expected:
- `empty_link_rows` should be 0 (or treated before rollout)
- baseline counts recorded in deploy notes

- [ ] **Step 2: Write UP migration file**

Include:
- two `ADD COLUMN IF NOT EXISTS`
- backfill statement
- `NOT NULL` enforcement
- check constraint creation

- [ ] **Step 3: Write DOWN migration file**

Include:

```sql
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_seen_window_chk;
ALTER TABLE jobs DROP COLUMN IF EXISTS last_seen_at;
ALTER TABLE jobs DROP COLUMN IF EXISTS first_seen_at;
```

- [ ] **Step 4: Dry-run migration on staging clone**

Run SQL in a non-production environment and capture:
- elapsed runtime
- rows updated in backfill
- lock wait or timeout events

### Task 2: Update ingest path

**Files:**
- Modify: `app/models/catalog.py` (`Job.insert_many`)
- Optional adjustment: `app/models/db.py` (`init_db`) to include `ADD COLUMN IF NOT EXISTS` safety net if startup bootstrap must remain self-healing
- Test: `tests/test_jobs_insert_many_seen_timestamps.py` (new)

- [ ] **Step 1: Extend insert column list**

Add `first_seen_at` and `last_seen_at` to `cols` and payload with `NOW()` values.

- [ ] **Step 2: Replace conflict action**

Change upsert from do-nothing to:

```sql
ON CONFLICT (link) DO UPDATE
SET last_seen_at = NOW()
```

- [ ] **Step 3: Add tests for first/last seen behavior**

Cover:
- New link insert sets both timestamps
- Re-insert same link keeps `first_seen_at` and advances `last_seen_at`
- Invariant `last_seen_at >= first_seen_at`

- [ ] **Step 4: Run targeted tests**

Run:

```bash
pytest tests/test_jobs_insert_many_seen_timestamps.py -v
```

Expected:
- all tests pass

### Task 3: Operational verification and release

**Files:**
- Deployment runbook entry (team-specific location)

- [ ] **Step 1: Deploy schema migration first**

Run UP SQL before app code deploy.

- [ ] **Step 2: Deploy application change second**

Release updated `Job.insert_many` conflict behavior.

- [ ] **Step 3: Post-deploy validation queries**

Run:

```sql
SELECT
  COUNT(*) FILTER (WHERE first_seen_at IS NULL) AS null_first_seen,
  COUNT(*) FILTER (WHERE last_seen_at IS NULL) AS null_last_seen,
  COUNT(*) FILTER (WHERE last_seen_at < first_seen_at) AS invalid_window
FROM jobs;
```

Expected:
- all three counts are `0`

- [ ] **Step 4: Duplicate-link recrawl probe**

Pick one known `link`, force a recrawl/import, then verify:

```sql
SELECT link, first_seen_at, last_seen_at
FROM jobs
WHERE link = '<known-link>';
```

Expected:
- `first_seen_at` unchanged
- `last_seen_at` updated to recent timestamp

---

## Risk Register

- Risk: large table backfill causes lock pressure.
  - Mitigation: run in low-traffic window; if needed batch by `id` ranges.
- Risk: `date` contains malformed values that cannot cast to `timestamptz`.
  - Mitigation: use guarded cast strategy or fallback to `NOW()` for non-castable rows.
- Risk: conflict updates increase write volume.
  - Mitigation: keep update set minimal (`last_seen_at` only), monitor write IOPS and query latency.

---

## Rollback Plan

- If app deploy causes regressions:
  - revert app code to prior `ON CONFLICT DO NOTHING` behavior
  - keep columns in place (safe additive state)
- If full rollback required:
  - execute DOWN SQL (drop check constraint and both columns)
  - only after confirming no downstream dependency has been introduced

---

## Approval Checklist

- [ ] Product owner approves schema change scope
- [ ] DBA/owner approves backfill strategy
- [ ] Staging migration runtime accepted
- [ ] Application cutover tests green
- [ ] Post-deploy validation query results archived
