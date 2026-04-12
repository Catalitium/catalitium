"""Tests for the smart discovery / explore feature.

Covers:
- Quality scoring (complete, empty, partial job dicts)
- Function categorization (Backend, Frontend, Other, etc.)
- Explore hub, remote companies, and function distribution routes
- Advanced job filters (remote, has_salary, freshness, function)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.catalog import (
    FUNCTION_CATEGORIES,
    categorize_function,
    compute_quality_score,
)


# ---------------------------------------------------------------------------
# Unit tests: compute_quality_score
# ---------------------------------------------------------------------------


class TestQualityScore:
    """Quality scoring with various input combinations."""

    def test_complete_job_near_max(self):
        now = datetime.now(timezone.utc)
        job = {
            "salary": "CHF 120k-160k",
            "job_description": "x" * 250,
            "city": "Zurich",
            "date": now.isoformat(),
            "company_name": "Acme Corp",
        }
        result = compute_quality_score(job)
        assert result["total"] == 100
        assert result["breakdown"]["salary"] == 25
        assert result["breakdown"]["description"] == 25
        assert result["breakdown"]["location"] == 20
        assert result["breakdown"]["freshness"] == 15
        assert result["breakdown"]["company"] == 15

    def test_empty_job_zero(self):
        result = compute_quality_score({})
        assert result["total"] == 0
        for v in result["breakdown"].values():
            assert v == 0

    def test_partial_salary_only(self):
        result = compute_quality_score({"salary": "USD 100k"})
        assert result["total"] == 25
        assert result["breakdown"]["salary"] == 25
        assert result["breakdown"]["description"] == 0

    def test_partial_description_and_company(self):
        result = compute_quality_score({
            "job_description": "A" * 201,
            "company_name": "TestCo",
        })
        assert result["total"] == 40
        assert result["breakdown"]["description"] == 25
        assert result["breakdown"]["company"] == 15

    def test_numeric_salary_accepted(self):
        result = compute_quality_score({"job_salary_range": 95000})
        assert result["breakdown"]["salary"] == 25

    def test_stale_date_no_freshness(self):
        old = datetime.now(timezone.utc) - timedelta(days=60)
        result = compute_quality_score({"date": old.isoformat()})
        assert result["breakdown"]["freshness"] == 0

    def test_recent_date_gets_freshness(self):
        recent = datetime.now(timezone.utc) - timedelta(days=5)
        result = compute_quality_score({"date": recent.isoformat()})
        assert result["breakdown"]["freshness"] == 15

    def test_yyyymmdd_date_format(self):
        recent = datetime.now(timezone.utc) - timedelta(days=2)
        date_str = recent.strftime("%Y%m%d")
        result = compute_quality_score({"date": date_str})
        assert result["breakdown"]["freshness"] == 15

    def test_total_capped_at_100(self):
        job = {
            "salary": "200k",
            "job_salary_range": "200k",
            "job_description": "x" * 300,
            "description": "y" * 300,
            "city": "Berlin",
            "date": datetime.now(timezone.utc).isoformat(),
            "company_name": "MegaCorp",
            "company": "MegaCorp",
        }
        result = compute_quality_score(job)
        assert result["total"] <= 100

    def test_whitespace_only_values_ignored(self):
        result = compute_quality_score({
            "salary": "   ",
            "city": "   ",
            "company_name": "   ",
        })
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# Unit tests: categorize_function
# ---------------------------------------------------------------------------


class TestCategorizeFunction:
    """Function category assignment from normalized job titles."""

    def test_backend_engineer(self):
        assert categorize_function("backend engineer") == "Backend"

    def test_frontend_developer(self):
        assert categorize_function("frontend developer") == "Frontend"

    def test_random_title_other(self):
        assert categorize_function("random title xyz") == "Other"

    def test_none_returns_other(self):
        assert categorize_function(None) == "Other"

    def test_empty_string_returns_other(self):
        assert categorize_function("") == "Other"

    def test_fullstack(self):
        assert categorize_function("full-stack developer") == "Fullstack"

    def test_ml_ai(self):
        assert categorize_function("machine learning engineer") == "ML/AI"

    def test_devops(self):
        assert categorize_function("devops engineer") == "DevOps/Infra"

    def test_data_engineer(self):
        assert categorize_function("data engineer") == "Data"

    def test_product_manager(self):
        assert categorize_function("product manager") == "Product"

    def test_security(self):
        assert categorize_function("security analyst") == "Security"

    def test_case_insensitive(self):
        assert categorize_function("BACKEND ENGINEER") == "Backend"

    def test_all_categories_have_keywords(self):
        for cat, keywords in FUNCTION_CATEGORIES.items():
            assert len(keywords) > 0, f"Category {cat} has no keywords"


# ---------------------------------------------------------------------------
# Route smoke tests
# ---------------------------------------------------------------------------


def test_explore_hub_returns_200(client):
    r = client.get("/explore")
    assert r.status_code == 200


def test_explore_remote_returns_200(client):
    r = client.get("/explore/remote-companies")
    assert r.status_code == 200


def test_explore_functions_returns_200(client):
    r = client.get("/explore/functions")
    assert r.status_code == 200


def test_jobs_with_remote_filter(client):
    r = client.get("/jobs?remote=1")
    assert r.status_code == 200


def test_jobs_with_has_salary_filter(client):
    r = client.get("/jobs?has_salary=1")
    assert r.status_code == 200


def test_jobs_with_freshness_filter(client):
    r = client.get("/jobs?freshness=7")
    assert r.status_code == 200


def test_jobs_with_function_filter(client):
    r = client.get("/jobs?function=Backend")
    assert r.status_code == 200


def test_jobs_combined_filters(client):
    r = client.get("/jobs?remote=1&has_salary=1&freshness=14&function=Frontend")
    assert r.status_code == 200


def test_explore_in_sitemap(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "/explore" in body
    assert "/explore/remote-companies" in body
    assert "/explore/functions" in body
