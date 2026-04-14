#!/usr/bin/env python3
"""Post-deploy smoke test against live https://catalitium.com.

Usage (from repo root):
    python tests/smoke_prod.py

Exit 0 if all checks pass; non-zero if any URL returns unexpected status.
Replaces tests/smoke_prod.ps1 (Windows-only).
"""

from __future__ import annotations

import sys

try:
    import httpx
except ImportError:
    print("[ERROR] httpx not installed. Run: pip install httpx", file=sys.stderr)
    sys.exit(1)

BASE = "https://catalitium.com"

CHECKS: list[tuple[str, str, int]] = [
    ("health", f"{BASE}/health", 200),
    ("jobs", f"{BASE}/jobs", 200),
    ("jobs_salary_min", f"{BASE}/jobs?salary_min=80000", 200),
    ("sitemap", f"{BASE}/sitemap.xml", 200),
]


def main() -> int:
    failed = False
    with httpx.Client(follow_redirects=True, timeout=15) as client:
        for name, url, expected in CHECKS:
            try:
                r = client.get(url)
                ok = r.status_code == expected
                status = "OK  " if ok else "FAIL"
                print(f"[{status}] {name:<20} {url} -> {r.status_code}")
                if not ok:
                    failed = True
            except Exception as exc:
                print(f"[FAIL] {name:<20} {url} -> ERROR: {exc}")
                failed = True

    if failed:
        print("\n[FAIL] One or more prod URLs did not return expected status.", file=sys.stderr)
        return 1
    print("\n[OK] All prod smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
