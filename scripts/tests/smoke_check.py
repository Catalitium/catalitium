"""
Lightweight smoke checks for search, subscribe, and analytics endpoints.
Uses a temporary SQLite DB and Flask test client.
Run: python scripts/smoke_check.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from pprint import pprint


def setup_app(tmp_db: str):
    # Ensure repository root on sys.path for 'app' imports
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.setdefault("FORCE_SQLITE", "1")
    os.environ.setdefault("SECRET_KEY", "smoke-secret")
    os.environ["DB_PATH"] = tmp_db
    from app.app import create_app
    app = create_app()
    return app


def seed_jobs(app):
    from app.models.db import init_db
    from app.models.db import Job
    rows = [
        {"job_title": "Software Engineer", "job_description": "Build APIs", "link": "https://example.com/1", "location": "Madrid, ES", "job_date": "2025-10-01", "date": "2025-10-01T10:00:00Z"},
        {"job_title": "Software Engineer 50% KPI", "job_description": "KPIs", "link": "https://example.com/2", "location": "Barcelona, ES", "job_date": "2025-10-02", "date": "2025-10-02T10:00:00Z"},
        {"job_title": "Data Engineer", "job_description": "ETL", "link": "https://example.com/3", "location": "Berlin, DE", "job_date": "2025-10-03", "date": "2025-10-03T10:00:00Z"},
    ]
    with app.app_context():
        init_db()
        Job.insert_many(rows)


def check_search(client):
    r = client.get("/?title=software&country=ES")
    assert r.status_code == 200, r.status_code
    html = r.get_data(as_text=True)
    assert "Software Engineer" in html
    r_api = client.get("/api/jobs?title=software&country=ES&per_page=10&page=1")
    assert r_api.status_code == 200
    data = r_api.get_json()
    assert isinstance(data, dict) and data.get("meta") and data.get("items")
    return {"page_ok": True, "api_items": len(data["items"]), "meta": data["meta"]}


def check_subscribe(client, app):
    rj = client.post("/subscribe.json", json={"email": "user@example.com"})
    assert rj.status_code == 200, rj.get_data(as_text=True)
    payload = rj.get_json() or {}
    assert payload.get("status") == "ok"

    rf = client.post("/subscribe", data={"email": "user@example.com"})
    assert rf.status_code in (301, 302, 303, 307, 308)

    # Verify subscriber persisted
    from app.models.db import get_db
    with app.app_context():
        db = get_db()
        if app.config.get("DB_BACKEND") == "postgres":
            with db.cursor() as cur:
                cur.execute("SELECT count(*) FROM subscribers")
                (cnt,) = cur.fetchone()
        else:
            cur = db.execute("SELECT count(*) FROM subscribers")
            row = cur.fetchone()
            cnt = row[0] if row else 0
    assert cnt >= 1
    return {"subscribe_json": "ok", "events": cnt}


def check_analytics(client):
    # Unified events/log route
    r1 = client.post("/events/log", json={
        "type": "job_view",
        "payload": {"job_id": "X1", "job_title": "Engineer", "company": "ACME", "location": "ES"}
    })
    assert r1.status_code == 200
    r2 = client.post("/events/log", json={
        "type": "search",
        "payload": {"raw_title": "software", "raw_country": "ES"}
    })
    assert r2.status_code == 200
    # Dedicated job_view endpoint
    r3 = client.post("/events/job_view", json={
        "job_id": "X2", "job_title": "Engineer", "company": "ACME", "location": "ES"
    })
    assert r3.status_code == 200
    return {"events_log_job_view": True, "events_log_search": True, "events_job_view": True}


def main():
    tmp = os.path.join("scripts", "tmp", "smoke_check.db")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    if os.path.exists(tmp):
        try:
            os.remove(tmp)
        except Exception:
            pass
    app = setup_app(tmp)
    seed_jobs(app)
    out = {}
    with app.test_client() as c:
        out["search"] = check_search(c)
        out["subscribe"] = check_subscribe(c, app)
        out["analytics"] = check_analytics(c)
        health = c.get("/ping").get_json()
        out["ping"] = health
    print("SMOKE SUMMARY:")
    pprint(out)


if __name__ == "__main__":
    main()
