import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.app import create_app
from app.models.db import Job, get_db


@pytest.fixture
def app_client(tmp_path_factory, monkeypatch):
    """Spin up a Flask test client backed by an isolated SQLite database (local fixture for these tests)."""
    db_path = tmp_path_factory.mktemp("catalitium-tests") / "main.db"
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("FORCE_SQLITE", "1")
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()
    app.config.update(TESTING=True)
    yield app, app.test_client()


def _insert_salary(app, geo_salary_id, location, median, currency):
    with app.app_context():
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO salary (geo_salary_id, location, median_salary, currency_ticker, loaded_at) VALUES (%s,%s,%s,%s,%s)",
                (geo_salary_id, location, median, currency, datetime.now(timezone.utc)),
            )


def _insert_job(app, **overrides):
    base = {
        "job_title": "Backend Engineer",
        "job_description": "Build resilient services.",
        "link": f"https://example.com/job/{uuid.uuid4().hex}",
        "location": "Berlin, DE",
        "company_name": "Catalitium",
        "date": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    with app.app_context():
        Job.insert_many([base])


def test_badge_shown_when_salary_exists(app_client):
    app, client = app_client
    # insert salary matching the job location
    geo_id = 999999
    _insert_salary(app, geo_id, "Berlin", 120000, "EUR")
    _insert_job(app, job_title="Berlin Backend", location="Berlin")
    resp = client.get('/')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # should show currency code and a range delimiter (en dash)
    assert "EUR" in html
    assert "\u2013" in html or "-" in html
    assert "median" in html


def test_badge_shows_not_available_when_no_salary(app_client):
    app, client = app_client
    _insert_job(app, job_title="No Salary Job", location="Unknown City")
    resp = client.get('/')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # when there is no salary, show 'Not available' text for the card
    assert "Not available" in html
