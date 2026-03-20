"""
Supabase Smoke Test
===================
Standalone script — no Flask required.
Reads DATABASE_URL from .env and runs 5 checks against Supabase.

Usage:
    python scripts/supabase_smoke_test.py
"""

import os
import sys
from pathlib import Path

# Load .env from project root
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    print("[WARN] python-dotenv not installed; reading raw env vars only")

try:
    import psycopg
except ImportError:
    print("[FAIL] psycopg not installed. Run: pip install 'psycopg[binary]'")
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or ""

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"

results = []

def check(label: str, ok: bool, detail: str = ""):
    icon = PASS if ok else FAIL
    line = f"  [{icon}] {label}"
    if detail:
        line += f"  >>  {detail}"
    print(line)
    results.append(ok)

# ── Check 0: .env loaded correctly ────────────────────────────────────────────

print("\n=== Supabase Smoke Test ===\n")

check(
    ".env DATABASE_URL is set",
    bool(DATABASE_URL),
    DATABASE_URL[:40] + "..." if DATABASE_URL else "MISSING"
)

if not DATABASE_URL:
    print("\n[FAIL] No DATABASE_URL. Check your .env file.\n")
    sys.exit(1)

# ── Connect ────────────────────────────────────────────────────────────────────

conn = None
try:
    conn = psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=10)
    check("TCP connection to Supabase", True, "connected")
except Exception as exc:
    check("TCP connection to Supabase", False, str(exc))
    print("\n[FAIL] Cannot connect. Verify DATABASE_URL and network.\n")
    sys.exit(1)

# ── Check 1: Basic SELECT 1 ────────────────────────────────────────────────────

try:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 AS ping")
        row = cur.fetchone()
    check("SELECT 1 ping", row[0] == 1, f"got {row[0]}")
except Exception as exc:
    check("SELECT 1 ping", False, str(exc))

# ── Check 2: List existing tables ─────────────────────────────────────────────

REQUIRED_TABLES = {"jobs", "subscribers", "api_keys"}
found_tables = set()

try:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)
        found_tables = {row[0] for row in cur.fetchall()}
    check("Can query pg_tables", True, f"{len(found_tables)} tables: {', '.join(sorted(found_tables)) or 'none'}")
except Exception as exc:
    check("Can query pg_tables", False, str(exc))

missing = REQUIRED_TABLES - found_tables
for table in sorted(REQUIRED_TABLES):
    exists = table in found_tables
    check(f"Table '{table}' exists", exists, "OK" if exists else "MISSING — needs to be created")

# ── Check 3: Row counts on existing tables ─────────────────────────────────────

for table in sorted(found_tables & REQUIRED_TABLES):
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(1) FROM {table}")
            count = cur.fetchone()[0]
        check(f"Row count on '{table}'", True, f"{count:,} rows")
    except Exception as exc:
        check(f"Row count on '{table}'", False, str(exc))

# ── Check 4: Write + rollback on subscribers ──────────────────────────────────

if "subscribers" in found_tables:
    TEST_EMAIL = "__smoke_test__@catalitium.test"
    try:
        with conn.cursor() as cur:
            # Clean up any leftover from a previous run
            cur.execute("DELETE FROM subscribers WHERE email = %s", [TEST_EMAIL])
            cur.execute(
                "INSERT INTO subscribers(email, created_at) VALUES(%s, NOW())",
                [TEST_EMAIL]
            )
            cur.execute("SELECT email FROM subscribers WHERE email = %s", [TEST_EMAIL])
            row = cur.fetchone()
            # Clean up
            cur.execute("DELETE FROM subscribers WHERE email = %s", [TEST_EMAIL])
        check("Write + read + delete on 'subscribers'", row is not None, "round-trip OK")
    except Exception as exc:
        check("Write + read + delete on 'subscribers'", False, str(exc))

# ── Summary ────────────────────────────────────────────────────────────────────

conn.close()

total = len(results)
passed = sum(results)
failed = total - passed

print(f"\n=== Result: {passed}/{total} checks passed", end="")
if failed:
    print(f"  ({failed} failed)")
else:
    print("  -- ALL GOOD")

if missing:
    print(f"\n{WARN}  Missing tables: {', '.join(sorted(missing))}")
    print("   Run the schema migration in Supabase SQL editor to create them.\n")

sys.exit(0 if failed == 0 else 1)
