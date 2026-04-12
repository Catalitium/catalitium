#!/usr/bin/env python3
"""Smoke-test Carl PDF extract + POST /carl/analyze + optional profiles row check.

Usage (PowerShell, from repo root ``worktrees/troy``)::

    $env:CARL_TEST_USER_ID = "<your auth.users id uuid>"
    python scripts/smoke_carl_pdf_profile.py

Optional::

    $env:CARL_TEST_PDF = "C:\\path\\to\\cv.pdf"

Requires ``DATABASE_URL`` / ``.env`` (see ``run.py`` fallback to main repo ``.env``).
"""

from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")
    load_dotenv(override=True)
    if not (ROOT / ".env").is_file():
        main_env = ROOT.parent.parent / ".env"
        if main_env.is_file():
            load_dotenv(dotenv_path=main_env, override=False)


def main() -> int:
    _load_env()
    os.environ.setdefault("FLASK_ENV", "development")
    os.environ.setdefault("ENV", "development")

    pdf = Path(os.environ.get("CARL_TEST_PDF", r"C:\Users\catal\Documents\Personal\Personal\JpgCvEng.pdf"))
    if not pdf.is_file():
        print("FAIL: PDF not found:", pdf, file=sys.stderr)
        return 2

    from werkzeug.datastructures import FileStorage

    from app.models.cv import CVExtractionError, extract_cv_from_upload

    raw = pdf.read_bytes()
    fs = FileStorage(stream=io.BytesIO(raw), filename=pdf.name, content_type="application/pdf")
    try:
        ev = extract_cv_from_upload(fs)
    except CVExtractionError as exc:
        print("FAIL: extract", exc.code, exc.message, file=sys.stderr)
        return 3
    print("extract_ok chars=", len(ev.text), "truncated=", ev.truncated)

    from app.models.db import SUPABASE_URL

    if not SUPABASE_URL:
        print("SKIP: no DATABASE_URL / SUPABASE_URL — load .env then rerun.")
        return 0

    from app.factory import create_app

    app = create_app()
    client = app.test_client()

    uid = (os.environ.get("CARL_TEST_USER_ID") or "00000000-0000-4000-8000-000000009991").strip()
    with client.session_transaction() as sess:
        sess["user"] = {"id": uid, "email": "smoke-carl@example.invalid"}

    r = client.get("/carl")
    if r.status_code != 200:
        print("FAIL: GET /carl", r.status_code, file=sys.stderr)
        return 4
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.get_data(as_text=True))
    if not m:
        print("FAIL: no csrf in /carl", file=sys.stderr)
        return 5
    csrf = m.group(1)

    data = {"csrf_token": csrf, "cv_file": (io.BytesIO(raw), pdf.name)}
    resp = client.post("/carl/analyze", data=data, headers={"X-CSRF-Token": csrf})
    print("POST /carl/analyze", resp.status_code)
    payload = resp.get_json(silent=True) or {}
    if resp.status_code != 200:
        print("body:", resp.get_data(as_text=True)[:800], file=sys.stderr)
        return 6
    if not payload.get("ok"):
        print("FAIL: API envelope", payload, file=sys.stderr)
        return 7
    analysis = (payload.get("data") or {}).get("analysis")
    if not analysis:
        print("FAIL: missing analysis in data", file=sys.stderr)
        return 8

    if os.environ.get("CARL_TEST_USER_ID"):
        from app.models.db import get_db

        verify_uid = os.environ["CARL_TEST_USER_ID"].strip()
        with app.app_context():
            db = get_db()
            with db.cursor() as cur:
                cur.execute(
                    "SELECT length(cv_extracted_text), cv_meta IS NOT NULL, cv_extracted_at IS NOT NULL "
                    "FROM profiles WHERE id = %s::uuid",
                    (verify_uid,),
                )
                row = cur.fetchone()
        if not row or row[0] is None or int(row[0] or 0) < 10:
            print("FAIL: profiles.cv_extracted_text missing or too short", row, file=sys.stderr)
            return 9
        print("db_ok len=", row[0], "has_meta=", row[1], "has_ts=", row[2])
    else:
        print("SKIP DB row check: set CARL_TEST_USER_ID to your Supabase auth user UUID.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
