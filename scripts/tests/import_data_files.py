#!/usr/bin/env python3
"""
Import all .csv and .txt files from ./data into ./data/catalitium.db as new tables,
then move the files into ./data/archive/.

Rules:
- Table name = filename stem (lowercased), e.g. salary.csv -> salary
- Columns are taken from header row; created as TEXT for safety
- Delimiter is auto-detected between [\t, ',', ';', '|']
- If a table already exists with the same name, it will be dropped and recreated

Usage:
  python scripts/import_data_files.py
"""

import os
import csv
import sqlite3
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "catalitium.db"
ARCHIVE_DIR = DATA_DIR / "archive"


def detect_delimiter(sample: str, default: str = ",") -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,;|")
        return dialect.delimiter
    except Exception:
        # Heuristic: prefer tab if found
        for d in ("\t", ",", ";", "|"):
            if d in sample:
                return d
        return default


def read_rows(path: Path):
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        head = f.read(4096)
        f.seek(0)
        delim = detect_delimiter(head)
        reader = csv.reader(f, delimiter=delim)
        try:
            headers = next(reader)
        except StopIteration:
            return [], []
        # Normalize headers: strip BOM/whitespace
        headers = [h.replace("\ufeff", "").strip() for h in headers]
        rows = [r for r in reader]
        return headers, rows


def sanitize_ident(s: str) -> str:
    # Keep simple identifiers; SQLite is lenient but avoid spaces/quotes
    out = []
    for ch in s:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("_")
    ident = "".join(out)
    if not ident:
        ident = "col"
    # Avoid leading digits
    if ident[0].isdigit():
        ident = "c_" + ident
    return ident


def ensure_archive():
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def import_file(conn: sqlite3.Connection, file_path: Path):
    table = file_path.stem.lower()
    headers, rows = read_rows(file_path)
    if not headers:
        print(f"- Skipping {file_path.name}: empty or no header")
        return False

    # Build schema
    cols = [(sanitize_ident(h) or f"col{i}") for i, h in enumerate(headers)]
    col_defs = ", ".join([f"{c} TEXT" for c in cols])
    cur = conn.cursor()
    # Drop existing table to ensure fresh import
    cur.execute("DROP TABLE IF EXISTS " + table)
    cur.execute("CREATE TABLE IF NOT EXISTS " + table + " (" + col_defs + ")")

    if rows:
        n = len(cols)
        norm_rows = []
        for r in rows:
            if len(r) < n:
                r = list(r) + [None] * (n - len(r))
            elif len(r) > n:
                r = r[:n]
            norm_rows.append(r)
        placeholders = ",".join(["?"] * n)
        cur.executemany(
            f"INSERT INTO {table} (" + ",".join(cols) + ") VALUES (" + placeholders + ")",
            norm_rows,
        )
    conn.commit()
    print(f"- Imported {file_path.name} -> table '{table}' ({len(rows)} rows)")
    return True


def main():
    if not DATA_DIR.exists():
        raise SystemExit("data/ directory not found")
    ensure_archive()

    # Connect to DB
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        targets = []
        for p in DATA_DIR.iterdir():
            if p.name.lower() in {"archive", DB_PATH.name.lower()}:
                continue
            if p.is_file() and p.suffix.lower() in {".csv", ".txt"}:
                targets.append(p)

        if not targets:
            print("No .csv or .txt files to import in data/.")
            return

        print(f"Importing into {DB_PATH}...")
        for fp in targets:
            ok = import_file(conn, fp)
            if ok:
                dest = ARCHIVE_DIR / fp.name
                try:
                    if dest.exists():
                        dest.unlink()
                except Exception:
                    pass
                shutil.move(str(fp), str(dest))
                print(f"  moved -> {dest}")
        print("Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
