#!/usr/bin/env python3
"""Migrate salary rows from local SQLite (data/catalitium.db) into Postgres (SUPABASE_URL).

Usage (PowerShell):
    $env:PYTHONPATH = 'C:\\path\\to\\repo'  # or set to repo root
    & .\.venv\Scripts\python.exe scripts\migrate_salary_to_pg.py

Run this from the project root so the `app` package can be imported.
"""
import sqlite3
from pathlib import Path
import os
import sys

# import project db helpers
try:
    from app.models import db as project_db
except Exception as e:
    print("Failed to import project db helpers:", e)
    print("Make sure you run this from the project root with PYTHONPATH set to the repo root.")
    raise

SQLITE_PATH = Path(project_db._sqlite_path())
print("Local sqlite path:", SQLITE_PATH)
if not SQLITE_PATH.exists():
    print("Local sqlite file not found. Aborting.")
    sys.exit(1)

# Read rows from local sqlite
conn = sqlite3.connect(str(SQLITE_PATH))
conn.row_factory = sqlite3.Row
with conn:
    cur = conn.execute("SELECT geo_salary_id, location, median_salary, min_salary, currency_ticker, city, country, region, remote_type, loaded_at FROM salary")
    rows = cur.fetchall()

print(f"Read {len(rows)} rows from local salary table")
if not rows:
    print("Nothing to migrate. Exiting.")
    sys.exit(0)

# Connect to Postgres
if not project_db.SUPABASE_URL:
    print("No SUPABASE_URL / DATABASE_URL configured in environment. Aborting.")
    sys.exit(1)

try:
    # Use a psycopg connection with prepare_threshold=0 to avoid server-side
    # prepared-statement behavior which can be invalidated by DDL and cause
    # "prepared statement \"_pg3_*\" does not exist" errors. Fall back to
    # the project's helper if psycopg isn't available.
    import psycopg
    pg_conn = psycopg.connect(project_db.SUPABASE_URL, autocommit=True, prepare_threshold=0)
except Exception as e:
    try:
        pg_conn = project_db._pg_connect()
    except Exception:
        print("Failed to connect to Postgres:", e)
        raise

# Ensure target table exists (create if not exists)
create_sql = '''
CREATE TABLE IF NOT EXISTS salary (
    geo_salary_id    INTEGER PRIMARY KEY,
    location         TEXT,
    median_salary    DOUBLE PRECISION,
    min_salary       DOUBLE PRECISION,
    currency_ticker  TEXT,
    city             TEXT,
    country          TEXT,
    region           TEXT,
    remote_type      TEXT,
    loaded_at        TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_salary_country     ON salary(country);
CREATE INDEX IF NOT EXISTS idx_salary_city        ON salary(city);
CREATE INDEX IF NOT EXISTS idx_salary_region      ON salary(region);
CREATE INDEX IF NOT EXISTS idx_salary_remote_type ON salary(remote_type);
'''
with pg_conn.cursor() as cur:
    try:
        # psycopg/psycopg3 does not allow executing multiple statements in a
        # single prepared statement. Split the DDL and execute statements one
        # at a time to avoid "cannot insert multiple commands into a prepared
        # statement" errors.
        for stmt in [s.strip() for s in create_sql.split(";") if s.strip()]:
            try:
                cur.execute(stmt)
            except Exception as stmt_exc:
                # Continue — we'll attempt to ensure columns below as a fallback
                print('DDL statement failed (continuing):', stmt_exc)
        
    except Exception as exc:
        # If something unexpected happened, note it and continue to the
        # column-add fallback logic below.
        print('Create table returned error (will attempt to ensure columns):', exc)

    # Ensure required columns exist (best-effort)
    expected_columns = {
        'geo_salary_id': 'INTEGER',
        'location': 'TEXT',
        'median_salary': 'DOUBLE PRECISION',
        'min_salary': 'DOUBLE PRECISION',
        'currency_ticker': 'TEXT',
        'city': 'TEXT',
        'country': 'TEXT',
        'region': 'TEXT',
        'remote_type': 'TEXT',
        'loaded_at': 'TIMESTAMP'
    }
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='salary'")
    existing = {row[0] for row in cur.fetchall()}
    for col, coltype in expected_columns.items():
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE salary ADD COLUMN IF NOT EXISTS {col} {coltype}")
                print('Added missing column to salary:', col)
            except Exception as e:
                print('Failed to add column', col, e)
    # Create indexes only for columns that now exist
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_salary_country     ON salary(country);",
        "CREATE INDEX IF NOT EXISTS idx_salary_city        ON salary(city);",
        "CREATE INDEX IF NOT EXISTS idx_salary_region      ON salary(region);",
        "CREATE INDEX IF NOT EXISTS idx_salary_remote_type ON salary(remote_type);",
    ]:
        try:
            cur.execute(idx_sql)
        except Exception as e:
            print('Index create skipped or failed:', e)

# After performing DDL (CREATE TABLE / ALTER TABLE / CREATE INDEX), close and reopen the
# Postgres connection so that any client-side prepared statements created earlier are
# reset. This avoids "prepared statement \"_pg3_0\" does not exist" errors when the
# driver invalidates prepared statements during DDL.
try:
    pg_conn.commit()
except Exception:
    # ignore commit errors here; we'll close and reopen anyway
    pass
try:
    pg_conn.close()
except Exception:
    pass
print('Reopening Postgres connection after DDL to avoid prepared-statement invalidation')
try:
    import psycopg
    pg_conn = psycopg.connect(project_db.SUPABASE_URL, autocommit=True, prepare_threshold=0)
except Exception:
    # fallback to project helper
    pg_conn = project_db._pg_connect()

# Upsert rows
insert_sql = '''
INSERT INTO salary (
    geo_salary_id, location, median_salary, min_salary, currency_ticker, city, country, region, remote_type, loaded_at
) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (geo_salary_id) DO UPDATE SET
    location = EXCLUDED.location,
    median_salary = EXCLUDED.median_salary,
    min_salary = EXCLUDED.min_salary,
    currency_ticker = EXCLUDED.currency_ticker,
    city = EXCLUDED.city,
    country = EXCLUDED.country,
    region = EXCLUDED.region,
    remote_type = EXCLUDED.remote_type,
    loaded_at = EXCLUDED.loaded_at;
'''

inserted = 0
updated = 0
failed = 0

# Close any pooled/reopened connection before doing per-row short-lived connects
try:
    pg_conn.close()
except Exception:
    pass

# Use a short-lived connection per row to avoid client-side prepared-statement
# lifecycle issues (safe for small migrations). Each iteration opens a fresh
# connection with prepare_threshold=0 when possible.
for r in rows:
    try:
        geo_id = int(r['geo_salary_id']) if r['geo_salary_id'] is not None else None
        vals = (
            geo_id,
            r['location'],
            float(r['median_salary']) if r['median_salary'] is not None else None,
            float(r['min_salary']) if r['min_salary'] is not None else None,
            r['currency_ticker'],
            r['city'],
            r['country'],
            r['region'],
            r['remote_type'],
            r['loaded_at'] or None,
        )
        # open fresh connection per-row
        try:
            import psycopg
            conn = psycopg.connect(project_db.SUPABASE_URL, autocommit=True, prepare_threshold=0)
        except Exception:
            conn = project_db._pg_connect()

        try:
            with conn.cursor() as cur:
                try:
                    cur.execute(insert_sql, vals)
                    inserted += 1
                except Exception as e:
                    msg = str(e).lower()
                    if 'no unique or exclusion constraint' in msg or 'target of conflicting' in msg or 'could not create unique' in msg:
                        # fallback safe upsert
                        cur.execute("SELECT 1 FROM salary WHERE geo_salary_id = %s", (geo_id,))
                        exists = cur.fetchone() is not None
                        if exists:
                            cur.execute(
                                """
                                UPDATE salary SET
                                    location = %s,
                                    median_salary = %s,
                                    min_salary = %s,
                                    currency_ticker = %s,
                                    city = %s,
                                    country = %s,
                                    region = %s,
                                    remote_type = %s,
                                    loaded_at = %s
                                WHERE geo_salary_id = %s
                                """,
                                (r['location'],
                                 float(r['median_salary']) if r['median_salary'] is not None else None,
                                 float(r['min_salary']) if r['min_salary'] is not None else None,
                                 r['currency_ticker'], r['city'], r['country'], r['region'], r['remote_type'], r['loaded_at'] or None, geo_id),
                            )
                            updated += 1
                        else:
                            cur.execute(
                                "INSERT INTO salary (geo_salary_id, location, median_salary, min_salary, currency_ticker, city, country, region, remote_type, loaded_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                vals,
                            )
                            inserted += 1
                    else:
                        failed += 1
                        print('Failed to upsert geo_salary_id', geo_id, e)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        failed += 1
        print('Failed processing row', r, e)

print(f"Done: attempted {len(rows)} rows, successes: {inserted + updated}, failures: {failed} (inserted={inserted}, updated={updated})")
print('Postgres connection closed.')
