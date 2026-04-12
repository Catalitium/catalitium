"""Tests for company intelligence pages: model helpers + routes."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(scope="module")
def _app():
    """Module-scoped app to avoid repeated init_db connections."""
    from app.factory import create_app
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def company_app(_app):
    return _app


@pytest.fixture()
def company_client(_app):
    return _app.test_client()


def _mock_cursor(fetchall=None, fetchone=None, description=None):
    cur = MagicMock()
    cur.fetchall.return_value = fetchall or []
    cur.fetchone.return_value = fetchone
    if description:
        cur.description = description
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    return cur


# ---------------------------------------------------------------------------
# Model layer: Job.company_list
# ---------------------------------------------------------------------------

def test_company_list_returns_list(company_app):
    from app.models.db import Job

    mock_cur = _mock_cursor(
        fetchall=[
            ("Acme Corp", 10, ["US", "DE"], "2026-04-01", 5),
            ("Beta Inc", 3, ["UK"], "2026-03-15", 1),
        ],
        description=[("company_name",), ("job_count",), ("countries",), ("latest_date",), ("salary_count",)],
    )
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with company_app.app_context():
        with patch("app.models.catalog.get_db", return_value=mock_conn):
            result = Job.company_list()

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["company_name"] == "Acme Corp"
    assert result[0]["job_count"] == 10
    assert result[0]["countries"] == ["US", "DE"]
    assert result[1]["company_name"] == "Beta Inc"


def test_company_list_with_search(company_app):
    from app.models.db import Job

    mock_cur = _mock_cursor(
        fetchall=[("Acme Corp", 10, ["US"], "2026-04-01", 5)],
        description=[("company_name",), ("job_count",), ("countries",), ("latest_date",), ("salary_count",)],
    )
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with company_app.app_context():
        with patch("app.models.catalog.get_db", return_value=mock_conn):
            result = Job.company_list(search="Acme")

    assert len(result) == 1
    executed_sql = mock_cur.execute.call_args[0][0]
    assert "ILIKE" in executed_sql


def test_company_list_handles_db_error(company_app):
    from app.models.db import Job
    with company_app.app_context():
        with patch("app.models.catalog.get_db", side_effect=Exception("db down")):
            result = Job.company_list()
    assert result == []


# ---------------------------------------------------------------------------
# Model layer: Job.company_count
# ---------------------------------------------------------------------------

def test_company_count_returns_int(company_app):
    from app.models.db import Job

    mock_cur = _mock_cursor(fetchone=(42,))
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with company_app.app_context():
        with patch("app.models.catalog.get_db", return_value=mock_conn):
            count = Job.company_count()

    assert count == 42


def test_company_count_handles_db_error(company_app):
    from app.models.db import Job
    with company_app.app_context():
        with patch("app.models.catalog.get_db", side_effect=Exception("db down")):
            count = Job.company_count()
    assert count == 0


# ---------------------------------------------------------------------------
# Model layer: Job.company_detail
# ---------------------------------------------------------------------------

def test_company_detail_returns_dict(company_app):
    from app.models.db import Job

    mock_cur = _mock_cursor(
        fetchone=("Acme Corp", 10, ["US", "DE"], ["software engineer", "data scientist"], "2026-04-01", 5),
        description=[("company_name",), ("job_count",), ("countries",), ("titles_norm",), ("latest_date",), ("salary_count",)],
    )
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with company_app.app_context():
        with patch("app.models.catalog.get_db", return_value=mock_conn):
            detail = Job.company_detail("Acme Corp")

    assert detail is not None
    assert detail["company_name"] == "Acme Corp"
    assert detail["job_count"] == 10


def test_company_detail_returns_none_for_empty(company_app):
    from app.models.db import Job

    mock_cur = _mock_cursor(
        fetchone=None,
        description=[("company_name",), ("job_count",), ("countries",), ("titles_norm",), ("latest_date",), ("salary_count",)],
    )
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with company_app.app_context():
        with patch("app.models.catalog.get_db", return_value=mock_conn):
            detail = Job.company_detail("Unknown Corp")

    assert detail is None


def test_company_detail_empty_name():
    from app.models.db import Job
    assert Job.company_detail("") is None
    assert Job.company_detail(None) is None


# ---------------------------------------------------------------------------
# Route: /companies returns 200
# ---------------------------------------------------------------------------

def test_companies_route_200(company_client):
    from app.models.db import Job
    with patch.object(Job, "company_count", return_value=0), \
         patch.object(Job, "company_list", return_value=[]):
        resp = company_client.get("/companies")
    assert resp.status_code == 200
    assert b"companies" in resp.data.lower() or b"Companies" in resp.data


def test_companies_route_with_search(company_client):
    from app.models.db import Job
    with patch.object(Job, "company_count", return_value=0), \
         patch.object(Job, "company_list", return_value=[]):
        resp = company_client.get("/companies?search=Acme")
    assert resp.status_code == 200


def test_companies_route_with_data(company_client):
    from app.models.db import Job
    fake_rows = [
        {
            "company_name": "Acme Corp",
            "job_count": 10,
            "countries": ["US"],
            "latest_date": "2026-04-01",
            "salary_count": 3,
        },
    ]
    with patch.object(Job, "company_count", return_value=1), \
         patch.object(Job, "company_list", return_value=fake_rows):
        resp = company_client.get("/companies")
    assert resp.status_code == 200
    assert b"Acme Corp" in resp.data


# ---------------------------------------------------------------------------
# Route: /companies/<slug> returns 200 or 404
# ---------------------------------------------------------------------------

def test_company_detail_route_404_unknown(company_client):
    from app.models.db import Job
    with patch.object(Job, "company_name_by_slug", return_value=None):
        resp = company_client.get("/companies/nonexistent-company-xyz")
    assert resp.status_code == 404


def test_company_detail_route_200(company_client):
    """Full integration mock: slug lookup + company_detail + company_jobs."""
    from app.models.db import Job
    from app.utils import slugify

    company_name = "Acme Corp"
    slug = slugify(company_name)

    fake_detail = {
        "company_name": company_name,
        "job_count": 5,
        "countries": ["US"],
        "titles_norm": ["software engineer"],
        "latest_date": "2026-04-01",
        "salary_count": 2,
    }
    fake_jobs = [
        {
            "id": 1,
            "job_title": "Software Engineer",
            "job_title_norm": "software engineer",
            "company_name": company_name,
            "job_description": "Build things",
            "location": "San Francisco, CA",
            "city": "San Francisco",
            "region": "CA",
            "country": "US",
            "link": "https://example.com/job/1",
            "date": "2026-04-01",
            "job_salary_range": "100k-150k",
        },
    ]

    with patch.object(Job, "company_name_by_slug", return_value=company_name), \
         patch.object(Job, "company_detail", return_value=fake_detail), \
         patch.object(Job, "company_jobs", return_value=fake_jobs):
        resp = company_client.get(f"/companies/{slug}")

    assert resp.status_code == 200
    assert company_name.encode() in resp.data
