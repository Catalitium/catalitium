import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app.app as app_module
from app.app import BLACKLIST_LINKS, create_app, _coerce_datetime, _job_is_new, _to_lc
from app.models.db import Job, get_db


@pytest.fixture
def app_client(tmp_path_factory, monkeypatch):
    """Spin up a Flask test client backed by an isolated SQLite database."""
    db_path = tmp_path_factory.mktemp("catalitium-tests") / "main.db"
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("FORCE_SQLITE", "1")
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()
    app.config.update(TESTING=True)
    yield app, app.test_client()


def _insert_job(app, **overrides):
    """Insert a job row and return its primary key."""
    base = {
        "job_title": "Backend Engineer",
        "job_description": "Build resilient services.",
        "link": "https://example.com/job/backend",
        "location": "Berlin, DE",
        "company_name": "Catalitium",
        "date": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    base.setdefault("job_id", f"seed-{uuid.uuid4().hex}")
    with app.app_context():
        Job.insert_many([base])
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT id FROM jobs WHERE link = %s", (base["link"],))
            row = cur.fetchone()
        return row[0] if row is not None else None


def _fetchone(app, sql, params=()):
    with app.app_context():
        db = get_db()
        with db.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def test_health_endpoint_reports_ok(app_client):
    app, client = app_client
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "db": "connected"}


def test_health_endpoint_handles_failure(app_client, monkeypatch):
    _, client = app_client

    def _raise():
        raise RuntimeError("db down")

    monkeypatch.setattr(app_module, "get_db", _raise)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.get_json() == {"status": "error", "db": "failed"}


def test_index_serves_database_results(app_client):
    app, client = app_client
    _insert_job(app, job_title="Search Result Engineer")
    response = client.get("/?title=Engineer&country=DE")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Search Result Engineer" in html
    row = _fetchone(app, "SELECT event_type FROM log_events ORDER BY id DESC LIMIT 1")
    assert row and row[0] == "search"


def test_location_filters_use_structured_fields(app_client):
    app, client = app_client
    _insert_job(
        app,
        job_title="Structured Country Match",
        location="",
        city="Munich",
        region="Bavaria",
        country="Germany",
        link="https://example.com/job/structured-country",
    )
    _insert_job(
        app,
        job_title="Structured City Match",
        location="",
        city="Hamburg",
        region="Hamburg",
        country=None,
        link="https://example.com/job/structured-city",
    )

    response_country = client.get("/?country=DE")
    assert response_country.status_code == 200
    html_country = response_country.get_data(as_text=True)
    assert "Structured Country Match" in html_country

    response_city = client.get("/?country=Hamburg")
    assert response_city.status_code == 200
    html_city = response_city.get_data(as_text=True)
    assert "Structured City Match" in html_city


def test_index_shows_demo_jobs_when_database_empty(app_client):
    app, client = app_client
    response = client.get("/")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Senior Software Engineer (AI)" in html
    row = _fetchone(app, "SELECT COUNT(1) FROM log_events")
    assert row[0] == 0


def test_api_jobs_respects_blacklist_and_pagination(app_client):
    app, client = app_client
    blocked_link = next(iter(BLACKLIST_LINKS))
    _insert_job(app, link=blocked_link, job_title="Analytics Scientist")
    response = client.get("/api/jobs?per_page=5")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["meta"]["per_page"] == 10
    assert payload["items"][0]["link"] is None


def test_subscribe_flow_persists_and_handles_duplicates(app_client):
    app, client = app_client
    job_id = _insert_job(app, link="https://example.com/apply-now", job_title="Apply Specialist")
    email = "apply@example.com"
    payload = {"email": email, "job_id": str(job_id)}

    first = client.post("/subscribe", json=payload)
    assert first.status_code == 200
    data_first = first.get_json()
    assert data_first["status"] == "ok"
    assert data_first["redirect"] == "https://example.com/apply-now"

    second = client.post("/subscribe", json=payload)
    assert second.status_code == 200
    data_second = second.get_json()
    assert data_second["status"] == "duplicate"
    assert data_second["redirect"] == "https://example.com/apply-now"

    stored = _fetchone(app, "SELECT email FROM subscribers")
    assert stored[0] == email

    event = _fetchone(app, "SELECT event_type, event_status FROM log_events ORDER BY id DESC LIMIT 1")
    assert event[0] == "subscribe"
    assert event[1] in {"ok", "duplicate"}


def test_subscribe_without_link_logs_email(app_client):
    app, client = app_client
    job_id = _insert_job(
        app,
        job_title="Frontend Without Link",
        link="",
        location="Remote",
    )
    email = "frontend@example.com"
    payload = {"email": email, "job_id": str(job_id)}

    response = client.post("/subscribe", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert not data.get("redirect")

    row = _fetchone(app, "SELECT email FROM subscribers WHERE email = %s", (email,))
    assert row and row[0] == email

    event = _fetchone(app, "SELECT event_type, event_status FROM log_events ORDER BY id DESC LIMIT 1")
    assert event[0] == "subscribe"
    assert event[1] == "ok"


def test_events_apply_persists_analytics_row(app_client):
    app, client = app_client
    job_id = _insert_job(app, job_title="Modal QA Lead", link="https://example.com/modal-job")
    payload = {
        "status": "modal_open",
        "job_id": str(job_id),
        "job_title": "Modal QA Lead",
        "job_company": "Catalitium",
        "job_location": "Remote",
        "job_link": "https://example.com/modal-job",
        "job_summary": "Modal smoke test.",
        "source": "web",
    }
    response = client.post("/events/apply", json=payload)
    assert response.status_code == 200
    row = _fetchone(
        app,
        """
        SELECT event_type, event_status, job_title_event, job_summary_event
        FROM log_events ORDER BY id DESC LIMIT 1
        """,
    )
    assert row[0] == "apply"
    assert row[1] == "modal_open"
    assert "Modal QA Lead" in (row[2] or "")
    assert "Modal smoke test." in (row[3] or "")


def test_salary_insights_marks_recent_jobs(app_client):
    app, client = app_client
    recent_iso = datetime.now(timezone.utc).isoformat()
    _insert_job(
        app,
        job_title="Machine Learning Engineer",
        location="Remote",
        link="https://example.com/ml-role",
        job_date=recent_iso,
        date=recent_iso,
    )
    response = client.get("/api/salary-insights?title=ml")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["count"] == 1
    assert payload["items"][0]["is_new"] is True


def test_utils_helpers_cover_regressions():
    iso = "2024-10-01T12:30:00"
    coerced = _coerce_datetime(iso)
    assert coerced.year == 2024
    assert _coerce_datetime("not-a-date") is None

    now = datetime.now(timezone.utc)
    assert _job_is_new(now, None) is True
    assert _job_is_new(now - timedelta(days=3), None) is False
    assert _to_lc("Senior ML Engineer") == "seniorMlEngineer"


def test_create_app_defaults_to_sqlite_when_no_supabase(monkeypatch, tmp_path):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FORCE_SQLITE", raising=False)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "local-default.db"))
    monkeypatch.setattr(app_module, "SUPABASE_URL", "")
    app = create_app()
    assert os.getenv("FORCE_SQLITE") == "1"
    assert app is not None
