"""
Smoke test: verify Postgres connectivity and readable access to ``contact_form`` and ``subscribers``.

Default mode uses tiny queries (metadata + ``SELECT 1 … LIMIT 1``) to keep egress low.
Optional ``--with-row-sample`` fetches at most one full row per table (can be large on JSONB).

Usage (from repo root, with DATABASE_URL or SUPABASE_URL in .env):

    python scripts/smoke_db_tables.py
    python scripts/smoke_db_tables.py --with-row-sample

Exit codes: 0 all OK, 1 connection/config failure, 2 one or more tables missing/inaccessible.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
except ImportError:
    pass

try:
    import psycopg
    from psycopg import sql
except ImportError:
    print("[FAIL] psycopg not installed.")
    sys.exit(1)

# Same env keys as app/models/db.py
_RAW = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or "").strip()
if not _RAW:
    print("[FAIL] Set DATABASE_URL or SUPABASE_URL.")
    sys.exit(1)

TABLES = ("contact_form", "subscribers")


def _connect():
    return psycopg.connect(_RAW, autocommit=True)


def _table_exists(cur, table: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        LIMIT 1
        """,
        (table,),
    )
    return cur.fetchone() is not None


def _column_summary(cur, table: str) -> str:
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        LIMIT 24
        """,
        (table,),
    )
    rows = cur.fetchall() or []
    if not rows:
        return "no columns (unexpected)"
    parts = [f"{n}:{t}" for n, t in rows[:12]]
    out = ", ".join(parts)
    if len(rows) > 12:
        out += "…"
    return out


def _smoke_table(cur, table: str, *, with_row_sample: bool) -> tuple[bool, str]:
    if not _table_exists(cur, table):
        return False, "table not found in public schema"

    cols = _column_summary(cur, table)

    q = sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(table))
    cur.execute(q)
    nonempty = cur.fetchone() is not None

    extra = "empty" if not nonempty else "has rows"
    if with_row_sample and nonempty:
        q2 = sql.SQL("SELECT * FROM {} LIMIT 1").format(sql.Identifier(table))
        cur.execute(q2)
        one = cur.fetchone()
        extra += f" ; row_repr_len={len(repr(one))}"

    return True, f"ok ({extra}); columns: {cols}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Postgres tables (low egress by default).")
    parser.add_argument(
        "--with-row-sample",
        action="store_true",
        help="Also SELECT * … LIMIT 1 per non-empty table (higher egress if rows are wide).",
    )
    args = parser.parse_args()

    print("[INFO] Connecting…")
    try:
        conn = _connect()
    except Exception as exc:
        print(f"[FAIL] Connection: {exc}")
        return 1

    failures = 0
    with conn.cursor() as cur:
        for table in TABLES:
            ok, detail = _smoke_table(cur, table, with_row_sample=bool(args.with_row_sample))
            tag = "OK" if ok else "FAIL"
            print(f"[{tag}] {table}: {detail}")
            if not ok:
                failures += 1

    conn.close()
    if failures:
        print(f"[DONE] {failures} table(s) failed.")
        return 2
    print("[DONE] All tables reachable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
