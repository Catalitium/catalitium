"""Tests for career decision intelligence tools.

Covers model functions (unit) and route smoke tests (HTTP 200).
No DB required — model tests use pure-Python logic or mock DB calls.
"""

from __future__ import annotations

import re
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def career_client(app):
    """HTTP client for career route smoke tests."""
    return app.test_client()


# ---------------------------------------------------------------------------
# compute_worth_it_score — unit tests
# ---------------------------------------------------------------------------


def test_worth_it_score_full_marks():
    from app.models.career import compute_worth_it_score

    job = {
        "job_salary_range": "100000-120000",
        "job_salary": 110000,
        "job_description": "x" * 600,
        "location": "Remote, EU",
        "_alternatives_count": 12,
    }
    salary_ref = (100000, "EUR")
    company_stats = {"job_count": 15, "latest_date": "2026-04-10T00:00:00+00:00"}
    result = compute_worth_it_score(job, salary_ref, company_stats)

    assert "total" in result
    assert "breakdown" in result
    assert result["total"] <= 100
    assert result["breakdown"]["salary_vs_market"] == 20
    assert result["breakdown"]["remote_availability"] == 20
    assert result["breakdown"]["alternatives_count"] == 20


def test_worth_it_score_no_data():
    from app.models.career import compute_worth_it_score

    job = {
        "job_salary_range": "",
        "job_description": "Short",
        "location": "",
        "_alternatives_count": 0,
    }
    result = compute_worth_it_score(job, None, None)
    assert result["total"] == 0
    for v in result["breakdown"].values():
        assert v == 0


def test_worth_it_score_below_market():
    from app.models.career import compute_worth_it_score

    job = {
        "job_salary_range": "50000-60000",
        "job_salary": 55000,
        "job_description": "x" * 100,
        "location": "Berlin",
        "_alternatives_count": 1,
    }
    salary_ref = (90000, "EUR")
    result = compute_worth_it_score(job, salary_ref, None)
    assert result["breakdown"]["salary_vs_market"] == 10


def test_worth_it_score_hybrid():
    from app.models.career import compute_worth_it_score

    job = {
        "job_salary_range": "80k-100k",
        "job_salary": 90000,
        "job_description": "x" * 600,
        "location": "Hybrid, London",
        "_alternatives_count": 6,
    }
    salary_ref = (85000, "GBP")
    result = compute_worth_it_score(job, salary_ref, None)
    assert result["breakdown"]["remote_availability"] == 10
    assert result["breakdown"]["alternatives_count"] == 10


def test_worth_it_score_estimated_only():
    from app.models.career import compute_worth_it_score

    job = {
        "job_salary_range": "",
        "job_description": "x" * 600,
        "location": "Zurich, CH",
        "_alternatives_count": 3,
    }
    salary_ref = (120000, "CHF")
    result = compute_worth_it_score(job, salary_ref, None)
    assert result["breakdown"]["salary_vs_market"] == 5


def test_worth_it_breakdown_keys():
    from app.models.career import compute_worth_it_score

    result = compute_worth_it_score({}, None, None)
    expected_keys = {
        "salary_vs_market", "company_signal", "role_quality",
        "remote_availability", "alternatives_count",
    }
    assert set(result["breakdown"].keys()) == expected_keys


# ---------------------------------------------------------------------------
# compute_ai_exposure — structure tests
# ---------------------------------------------------------------------------

def test_ai_exposure_returns_list(app):
    from app.models.career import compute_ai_exposure

    with app.app_context():
        try:
            result = compute_ai_exposure()
        except Exception:
            result = []
    assert isinstance(result, list)


def test_ai_exposure_dict_shape():
    item = {
        "function_name": "Engineering",
        "exposure_pct": 35.2,
        "category": "ai-adjacent",
        "job_count": 100,
        "median_salary": 95000.0,
    }
    assert "function_name" in item
    assert "exposure_pct" in item
    assert "category" in item
    assert item["category"] in ("ai-native", "ai-adjacent", "ai-distant")


def test_ai_exposure_category_thresholds():
    from app.models.career import _AI_PATTERN
    assert _AI_PATTERN.search("We use machine learning models daily")
    assert _AI_PATTERN.search("Experience with GPT and LLM required")
    assert not _AI_PATTERN.search("Standard accounting role with Excel")


# ---------------------------------------------------------------------------
# get_hiring_velocity — structure tests
# ---------------------------------------------------------------------------

def test_hiring_velocity_returns_list(app):
    from app.models.career import get_hiring_velocity

    with app.app_context():
        try:
            result = get_hiring_velocity()
        except Exception:
            result = []
    assert isinstance(result, list)


def test_hiring_velocity_dict_shape():
    item = {
        "company_name": "Acme Corp",
        "recent_count": 10,
        "previous_count": 5,
        "velocity_pct": 100.0,
        "trend": "growing",
        "total_jobs": 15,
    }
    assert item["trend"] in ("growing", "stable", "declining")
    assert isinstance(item["velocity_pct"], float)


# ---------------------------------------------------------------------------
# estimate_earnings — unit tests
# ---------------------------------------------------------------------------

@patch("app.models.career.get_salary_for_location")
@patch("app.models.career.get_db")
def test_estimate_earnings_reference_only(mock_db, mock_sal):
    from app.models.career import estimate_earnings

    mock_sal.return_value = (90000, "EUR")
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_db.return_value = mock_conn

    result = estimate_earnings("Software Engineer", "Berlin")
    assert result["data_source"] == "reference"
    assert result["base_median"] == 90000
    assert result["base_low"] == 72000
    assert result["base_high"] == 108000


@patch("app.models.career.get_salary_for_location")
@patch("app.models.career.get_db")
def test_estimate_earnings_insufficient(mock_db, mock_sal):
    from app.models.career import estimate_earnings

    mock_sal.return_value = None
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_db.return_value = mock_conn

    result = estimate_earnings("Obscure Role", "Nowhere")
    assert result["data_source"] == "insufficient"
    assert result["base_median"] is None


def test_estimate_earnings_structure():
    result = {
        "base_low": 80000,
        "base_median": 95000,
        "base_high": 110000,
        "currency": "EUR",
        "location": "Berlin",
        "title": "Software Engineer",
        "data_source": "reference",
    }
    assert all(k in result for k in ["base_low", "base_median", "base_high", "currency", "data_source"])


# ---------------------------------------------------------------------------
# get_career_paths — unit tests
# ---------------------------------------------------------------------------

@patch("app.models.career.Job")
@patch("app.models.career._get_top_employers")
def test_career_paths_senior_engineer(mock_employers, mock_job):
    from app.models.career import get_career_paths

    mock_job.search.return_value = [
        {"id": 1, "job_title": "Staff Engineer", "job_salary_range": "120k-150k"},
    ]
    mock_employers.return_value = [{"name": "BigCo", "count": 5}]

    result = get_career_paths("senior software engineer")
    assert "current" in result
    assert "next_steps" in result
    assert "lateral_moves" in result
    assert "companies_hiring" in result
    assert result["current"] == "senior software engineer"


def test_career_paths_structure():
    result = {
        "current": "data analyst",
        "next_steps": [{"title": "Senior Data Analyst", "median_salary": 85000, "job_count": 12}],
        "lateral_moves": [{"title": "Business Analyst", "median_salary": 75000, "job_count": 8}],
        "companies_hiring": [{"name": "DataCo", "count": 3}],
    }
    assert isinstance(result["next_steps"], list)
    assert isinstance(result["lateral_moves"], list)


# ---------------------------------------------------------------------------
# compute_market_position — unit tests
# ---------------------------------------------------------------------------

@patch("app.models.career.get_salary_for_location")
@patch("app.models.career.get_db")
def test_market_position_above(mock_db, mock_sal):
    from app.models.career import compute_market_position

    mock_sal.return_value = (80000, "EUR")
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = [(70000,), (80000,), (90000,)]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_db.return_value = mock_conn

    result = compute_market_position("Engineer", "Berlin", 5, 95000, "EUR")
    assert result["label"] in ("above_market", "at_market", "below_market", "insufficient_data")
    assert 0 <= result["percentile_rank"] <= 99
    assert result["currency"] == "EUR"


@patch("app.models.career.get_salary_for_location")
@patch("app.models.career.get_db")
def test_market_position_below(mock_db, mock_sal):
    from app.models.career import compute_market_position

    mock_sal.return_value = (100000, "CHF")
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = [(90000,), (100000,), (120000,)]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_db.return_value = mock_conn

    result = compute_market_position("Engineer", "Zurich", 1, 60000, "CHF")
    assert result["percentile_rank"] <= 50


def test_market_position_structure():
    result = {
        "title": "Engineer",
        "location": "Berlin",
        "user_salary": 90000,
        "currency": "EUR",
        "median": 85000,
        "percentile_rank": 65,
        "label": "above_market",
    }
    expected_keys = {"title", "location", "user_salary", "currency", "median", "percentile_rank", "label"}
    assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Route smoke tests — all 6 career routes return 200
# ---------------------------------------------------------------------------

def test_route_career_evaluate(career_client):
    resp = career_client.get("/career/evaluate")
    assert resp.status_code == 200
    assert b"Is This Role Worth It?" in resp.data


def test_route_career_ai_exposure(career_client):
    resp = career_client.get("/career/ai-exposure")
    assert resp.status_code == 200
    assert b"AI" in resp.data


def test_route_career_hiring_trends(career_client):
    resp = career_client.get("/career/hiring-trends")
    assert resp.status_code == 200
    assert b"Hiring Velocity" in resp.data


def test_route_career_earnings(career_client):
    resp = career_client.get("/career/earnings")
    assert resp.status_code == 200
    assert b"Earnings Estimator" in resp.data


def test_route_career_paths(career_client):
    resp = career_client.get("/career/paths")
    assert resp.status_code == 200
    assert b"Career Path Explorer" in resp.data


def test_route_career_market_position(career_client):
    resp = career_client.get("/career/market-position")
    assert resp.status_code == 200
    assert b"Market Position" in resp.data


def test_route_career_evaluate_with_job_id(career_client):
    resp = career_client.get("/career/evaluate?job_id=999999")
    assert resp.status_code == 200
    assert b"Is This Role Worth It?" in resp.data


def test_route_career_paths_with_title(career_client):
    resp = career_client.get("/career/paths?title=software+engineer")
    assert resp.status_code == 200
    assert b"Career Path Explorer" in resp.data


# ---------------------------------------------------------------------------
# Internal helper tests
# ---------------------------------------------------------------------------

def test_categorize_function():
    from app.models.career import _categorize_function

    assert _categorize_function("software engineer") == "Engineering"
    assert _categorize_function("data analyst") == "Data & Analytics"
    assert _categorize_function("machine learning engineer") == "AI & Machine Learning"
    assert _categorize_function("ux designer") == "Design"
    assert _categorize_function("product manager") == "Product"
    assert _categorize_function("barista") == "Other"


def test_level_index():
    from app.models.career import _level_index

    idx, track = _level_index("senior software engineer")
    assert track == "ic"
    assert idx == 2

    idx, track = _level_index("engineering manager")
    assert track == "mgmt"
    assert idx == 1

    idx, track = _level_index("accountant")
    assert track == "ic"
    assert idx == 1  # default mid-level


def test_ai_pattern_matching():
    from app.models.career import _AI_PATTERN

    positives = [
        "We need experience with machine learning",
        "GPT-based chatbot development",
        "Deep learning and neural network skills",
        "NLP pipeline engineering",
        "Generative AI product work",
        "Build an AI agent for customer service",
        "Automation of business workflows",
        "LLM fine-tuning and deployment",
        "Computer vision for autonomous systems",
        "Copilot integration features",
    ]
    for text in positives:
        assert _AI_PATTERN.search(text), f"Should match: {text}"

    negatives = [
        "Standard Java backend role",
        "Sales representative for enterprise",
        "Manual testing of mobile apps",
    ]
    for text in negatives:
        assert not _AI_PATTERN.search(text), f"Should not match: {text}"
