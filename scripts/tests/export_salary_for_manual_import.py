#!/usr/bin/env python3
"""Export local SQLite salary table to CSV and SQL insert file for manual import.

Produces:
 - scripts/output/salary_export.csv
 - scripts/output/salary_insert.sql

The SQL file uses INSERT ... ON CONFLICT (geo_salary_id) DO UPDATE ... to help
with idempotent imports. If your target Postgres does not have a unique
constraint on geo_salary_id, you can either add one in Supabase or run the SQL
file as-is and it will attempt to insert/update rows (may fail if constraint
absent). The CSV is safe for manual imports via Supabase dashboard or psql \copy.
"""
from pathlib import Path
import sqlite3
import csv
import os
from app.models import db as project_db

OUT_DIR = Path(__file__).resolve().parents[0] / 'output'
OUT_DIR.mkdir(parents=True, exist_ok=True)
SQLITE_PATH = Path(project_db._sqlite_path())
if not SQLITE_PATH.exists():
    print('Local sqlite not found at', SQLITE_PATH)
    raise SystemExit(1)

conn = sqlite3.connect(str(SQLITE_PATH))
conn.row_factory = sqlite3.Row
with conn:
    cur = conn.execute("SELECT geo_salary_id, location, median_salary, min_salary, currency_ticker, city, country, region, remote_type, loaded_at FROM salary")
    rows = cur.fetchall()

csv_path = OUT_DIR / 'salary_export.csv'
sql_path = OUT_DIR / 'salary_insert.sql'

with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
    writer = csv.writer(fh)
    writer.writerow(['geo_salary_id','location','median_salary','min_salary','currency_ticker','city','country','region','remote_type','loaded_at'])
    for r in rows:
        writer.writerow([
            r['geo_salary_id'], r['location'], r['median_salary'], r['min_salary'], r['currency_ticker'], r['city'], r['country'], r['region'], r['remote_type'], r['loaded_at']
        ])

with open(sql_path, 'w', encoding='utf-8') as fh:
    fh.write('-- Generated INSERT statements for salary table\n')
    fh.write('-- Consider adding a unique constraint on geo_salary_id in the target DB for ON CONFLICT to work:\n')
    fh.write('-- ALTER TABLE salary ADD CONSTRAINT salary_geo_salary_id_unique UNIQUE (geo_salary_id);\n\n')
    for r in rows:
        geo_id = r['geo_salary_id'] if r['geo_salary_id'] is not None else 'NULL'
        vals = (
            geo_id,
            r['location'] or '',
            r['median_salary'] if r['median_salary'] is not None else 'NULL',
            r['min_salary'] if r['min_salary'] is not None else 'NULL',
            (r['currency_ticker'] or ''),
            (r['city'] or ''),
            (r['country'] or ''),
            (r['region'] or ''),
            (r['remote_type'] or ''),
            (r['loaded_at'] or 'NULL'),
        )
        # safe SQL string encoding for simple ASCII; for robust escaping use parameterized execution
        def q(v):
            if v is None or v == 'NULL':
                return 'NULL'
            return "'" + str(v).replace("'", "''") + "'"
        fh.write('INSERT INTO salary (geo_salary_id, location, median_salary, min_salary, currency_ticker, city, country, region, remote_type, loaded_at) VALUES (' + ','.join([q(vals[0]), q(vals[1]), q(vals[2]), q(vals[3]), q(vals[4]), q(vals[5]), q(vals[6]), q(vals[7]), q(vals[8]), q(vals[9])]) + ')')
        fh.write(' ON CONFLICT (geo_salary_id) DO UPDATE SET location = EXCLUDED.location, median_salary = EXCLUDED.median_salary, min_salary = EXCLUDED.min_salary, currency_ticker = EXCLUDED.currency_ticker, city = EXCLUDED.city, country = EXCLUDED.country, region = EXCLUDED.region, remote_type = EXCLUDED.remote_type, loaded_at = EXCLUDED.loaded_at;\n')

print('Wrote CSV to', csv_path)
print('Wrote SQL to', sql_path)
print('Done. Use the CSV for import via Supabase UI or run the SQL in Supabase SQL editor.')
