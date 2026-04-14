#!/usr/bin/env python3
"""Unified smoke runner — one entry point for local / CI health checks.

Usage (from repo root):

    python tests/smoke.py --section routes
    python tests/smoke.py --section all

Sections:
  db        — tests/smoke_db_tables.py
  routes    — tests/smoke_routes_http.py
  carl      — tests/smoke_carl_pdf_profile.py
  supabase  — tests/supabase_smoke_test.py
  smtp      — tests/smtp_smoke_test.py (sends mail if env configured)
  all       — run every section in order; exit 1 if any fails

Run the sections that match what you changed (DB vs routes vs integrations).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent  # all smoke scripts live in tests/

SECTION_SCRIPTS: dict[str, Path] = {
    "db": SCRIPTS / "smoke_db_tables.py",
    "routes": SCRIPTS / "smoke_routes_http.py",
    "carl": SCRIPTS / "smoke_carl_pdf_profile.py",
    "supabase": SCRIPTS / "supabase_smoke_test.py",
    "smtp": SCRIPTS / "smtp_smoke_test.py",
}

ORDER_ALL = ("db", "routes", "carl", "supabase", "smtp")


def _run_script(label: str, script: Path) -> int:
    if not script.is_file():
        print(f"[FAIL] {label}: missing script {script}", file=sys.stderr)
        return 1
    print(f"\n=== smoke.py :: {label} :: {script.name} ===\n", flush=True)
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        print(f"\n[FAIL] {label} exited with code {proc.returncode}", file=sys.stderr)
    else:
        print(f"\n[OK] {label}")
    return int(proc.returncode or 0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run Catalitium smoke scripts by section.")
    p.add_argument(
        "--section",
        choices=list(SECTION_SCRIPTS.keys()) + ["all"],
        default="routes",
        help="Which smoke to run (default: routes)",
    )
    args = p.parse_args(argv)

    if args.section == "all":
        failed: list[str] = []
        for key in ORDER_ALL:
            script = SECTION_SCRIPTS[key]
            rc = _run_script(key, script)
            if rc != 0:
                failed.append(f"{key} (exit {rc})")
        if failed:
            print("\n[FAIL] smoke.py --section all:", file=sys.stderr)
            for line in failed:
                print("  -", line, file=sys.stderr)
            return 1
        print("\n[OK] smoke.py --section all: every section passed.")
        return 0

    return _run_script(args.section, SECTION_SCRIPTS[args.section])


if __name__ == "__main__":
    raise SystemExit(main())
