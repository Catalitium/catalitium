#!/usr/bin/env python3
"""
Seed selected tables from local SQLite (data/catalitium.db) into Postgres (DATABASE_URL).

Usage:
  python scripts/seed_to_postgres.py --tables salary,jobs --truncate

Notes:
- Creates table 'salary' in Postgres if missing (compatible with CSV columns).
- Assumes Postgres 'jobs' table already created by init_db(); inserts with ON CONFLICT(link) DO NOTHING.
- Requires psycopg (v3) and access to DATABASE_URL (sslmode=require recommended).
"""

import argparse
import os
import sqlite3
from pathlib import Path

try:
    import psycopg
except Exception as e:
    psycopg = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "catalitium.db"


def pg_connect(url: str):
    if not psycopg:
        raise RuntimeError("psycopg is required to seed Postgres. Install it and retry.")
    if url.startswith("postgres") and "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = url + sep + "sslmode=require"
    return psycopg.connect(url, autocommit=True)


def ensure_salary_table_pg(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS salary (
            GeoSalaryId TEXT,
            Location TEXT,
            MedianSalary TEXT,
            MinSalary TEXT,
            CurrencyTicker TEXT,
            City TEXT,
            Country TEXT,
            Region TEXT,
            RemoteType TEXT
        );
        """
    )


def seed_salary(sqlite_conn: sqlite3.Connection, pg_conn, truncate: bool = False):
    rows = sqlite_conn.execute(
        "SELECT GeoSalaryId,Location,MedianSalary,MinSalary,CurrencyTicker,City,Country,Region,RemoteType FROM salary"
    ).fetchall()
    with pg_conn.cursor() as cur:
        ensure_salary_table_pg(cur)
        if truncate:
            cur.execute("TRUNCATE TABLE salary")
        before = cur.execute("SELECT COUNT(1) FROM salary").fetchone()[0]
        q = (
            "INSERT INTO salary(GeoSalaryId,Location,MedianSalary,MinSalary,CurrencyTicker,City,Country,Region,RemoteType)"
            " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        )
        for r in rows:
            cur.execute(q, r)
        after = cur.execute("SELECT COUNT(1) FROM salary").fetchone()[0]
    print(f"Seeded salary: +{after - before} rows (from {len(rows)} candidates)")


def seed_jobs(sqlite_conn: sqlite3.Connection, pg_conn):
    # Pull from SQLite jobs table
    rows = sqlite_conn.execute(
        """
        SELECT
            job_id,
            job_title,
            job_title_norm,
            normalized_job,
            company_name,
            job_description,
            location,
            city,
            region,
            country,
            geo_id,
            robot_code,
            link,
            salary,
            date
        FROM jobs
        """
    ).fetchall()
    with pg_conn.cursor() as cur:
        # Ensure jobs exists (do not enforce unique index here to avoid failing on existing duplicates)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id SERIAL PRIMARY KEY,
                job_id TEXT,
                job_title TEXT,
                job_title_norm TEXT,
                normalized_job TEXT,
                company_name TEXT,
                job_description TEXT,
                location TEXT,
                city TEXT,
                region TEXT,
                country TEXT,
                geo_id TEXT,
                robot_code INTEGER NOT NULL DEFAULT 0,
                link TEXT,
                salary TEXT,
                date TEXT
            );
            """
        )
        # Insert rows additively, skip if link already exists (without requiring a unique index)
        before = cur.execute("SELECT COUNT(1) FROM jobs").fetchone()[0]

        base_q = (
            "INSERT INTO jobs("
            "job_id, job_title, job_title_norm, normalized_job, company_name, job_description, "
            "location, city, region, country, geo_id, robot_code, link, salary, date"
            ") "
            "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s "
            "WHERE NOT EXISTS (SELECT 1 FROM jobs j WHERE j.link = %s)"
        )
        for i, row in enumerate(rows):
            q = base_q + f" /*seed_{i}*/"
            cur.execute(q, tuple(list(row) + [row[12]]))
        after = cur.execute("SELECT COUNT(1) FROM jobs").fetchone()[0]
    print(f"Seeded jobs: +{after - before} rows (from {len(rows)} candidates)")


def main():
    ap = argparse.ArgumentParser(description="Seed tables from SQLite to Postgres")
    ap.add_argument("--tables", default="salary", help="Comma-separated list: salary,jobs")
    ap.add_argument("--truncate", action="store_true", help="Truncate target tables before insert (where applicable)")
    args = ap.parse_args()

    tables = {t.strip().lower() for t in args.tables.split(",") if t.strip()}
    db_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL (or SUPABASE_URL) is required for Postgres destination")

    if not DB_PATH.exists():
        raise SystemExit(f"SQLite DB not found: {DB_PATH}")

    print(f"Connecting to SQLite: {DB_PATH}")
    sqlite_conn = sqlite3.connect(str(DB_PATH))
    try:
        print("Connecting to Postgres...")
        pg_conn = pg_connect(db_url)
        try:
            if "salary" in tables:
                seed_salary(sqlite_conn, pg_conn, truncate=args.truncate)
            if "jobs" in tables:
                seed_jobs(sqlite_conn, pg_conn)
        finally:
            pg_conn.close()
    finally:
        sqlite_conn.close()


if __name__ == "__main__":
    main()
