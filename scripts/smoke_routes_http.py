"""
HTTP smoke: exercise key routes via Flask test_client (no live server).

Requires DATABASE_URL (or SUPABASE_URL) like the main app — loads .env from repo root.

Usage (from repo root):

    python scripts/smoke_routes_http.py

Exit: 0 all checks passed, 1 failure.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env", override=True)
except ImportError:
    pass

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from app.app import create_app

    app = create_app()

    client = app.test_client()
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}{(': ' + detail) if detail else ''}")

    r = client.get("/health")
    check("/health status", r.status_code == 200, f"got {r.status_code}")
    if r.is_json:
        payload = r.get_json() or {}
        inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        ok = payload.get("ok") is True or inner.get("status") == "ok"
        check("/health json payload", ok, str(payload)[:240])

    r = client.get("/jobs")
    check("/jobs status", r.status_code == 200, f"got {r.status_code}")

    r = client.get("/jobs?salary_min=80000")
    check("/jobs?salary_min= status", r.status_code == 200, f"got {r.status_code}")
    html = r.get_data(as_text=True)
    m = re.search(r'<link rel="next" href="([^"]+)"', html)
    if m and "page=2" in m.group(1):
        check("next link keeps salary_min", "salary_min=" in m.group(1), m.group(1)[:120])

    r = client.get("/sitemap.xml")
    check("/sitemap.xml status", r.status_code == 200, f"got {r.status_code}")
    data = r.get_data(as_text=True)
    check("/sitemap.xml body", "urlset" in data and "<loc>" in data, "missing urlset/loc")
    cc = r.headers.get("Cache-Control", "")
    check("/sitemap.xml Cache-Control", "max-age=" in cc, cc or "missing header")

    r = client.get("/jobs?title=developer")
    html = r.get_data(as_text=True) if r.status_code == 200 else ""
    m = re.search(r'href="(/jobs/\d[^"]*)"', html)
    if m:
        path = m.group(1)
        rj = client.get(path)
        check(f"job detail {path}", rj.status_code == 200, f"got {rj.status_code}")
    else:
        check("job detail sample", False, "no /jobs/<id>-slug link found in listing HTML")

    if failures:
        print("[FAIL] HTTP smoke:")
        for line in failures:
            print("  -", line)
        return 1
    print("[OK] HTTP smoke: /health, /jobs, salary_min listing, /sitemap.xml, one job detail")
    return 0


if __name__ == "__main__":
    sys.exit(main())
