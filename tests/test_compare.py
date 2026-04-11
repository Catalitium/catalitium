"""Tests for the compare scoring engine and compare/tracker routes."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from app.models.compare import score_job, compare_jobs


# ---------------------------------------------------------------------------
# score_job unit tests
# ---------------------------------------------------------------------------

class TestScoreJob:
    def test_full_data_max_score(self):
        """A job with all signals present should score 100."""
        job = {
            "job_salary_range": "120k-150k",
            "salary_min": 120_000,
            "date": (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d"),
            "location": "Remote, US",
            "job_description": "x" * 250,
        }
        result = score_job(job)
        assert result["total"] == 100
        assert all(v > 0 for v in result["breakdown"].values())

    def test_empty_job(self):
        """An empty dict should score 0."""
        result = score_job({})
        assert result["total"] == 0
        assert all(v == 0 for v in result["breakdown"].values())

    def test_partial_data(self):
        """Only some signals present."""
        job = {
            "job_salary_range": "100k",
            "location": "Berlin, DE",
            "job_description": "Short desc",
        }
        result = score_job(job)
        assert result["breakdown"]["salary_present"] == 25
        assert result["breakdown"]["remote"] == 0
        assert result["breakdown"]["description_quality"] == 0
        assert result["total"] == 25

    def test_stale_job_no_freshness(self):
        """A job older than 14 days gets 0 freshness."""
        job = {
            "date": (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"),
        }
        result = score_job(job)
        assert result["breakdown"]["freshness"] == 0

    def test_fresh_job_gets_freshness(self):
        """A job posted today gets the freshness score."""
        job = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        result = score_job(job)
        assert result["breakdown"]["freshness"] == 20

    def test_custom_weights(self):
        """Custom weights override defaults."""
        job = {"location": "Remote"}
        result = score_job(job, weights={"remote": 50})
        assert result["breakdown"]["remote"] == 50

    def test_remote_case_insensitive(self):
        """Remote detection is case-insensitive."""
        job = {"location": "REMOTE - USA"}
        result = score_job(job)
        assert result["breakdown"]["remote"] == 15

    def test_description_quality_threshold(self):
        """Exactly 200 chars should NOT pass, 201 should."""
        short = {"job_description": "a" * 200}
        long = {"job_description": "a" * 201}
        assert score_job(short)["breakdown"]["description_quality"] == 0
        assert score_job(long)["breakdown"]["description_quality"] == 20

    def test_salary_confidence_via_estimated(self):
        """estimated_salary flag triggers salary_confidence."""
        job = {"estimated_salary": True}
        result = score_job(job)
        assert result["breakdown"]["salary_confidence"] == 20


# ---------------------------------------------------------------------------
# compare_jobs unit tests
# ---------------------------------------------------------------------------

class TestCompareJobs:
    def test_ordering(self):
        """Jobs should be returned sorted by total descending."""
        jobs = [
            {"location": "Berlin"},
            {"location": "Remote", "job_salary_range": "100k", "salary_min": 100_000,
             "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
             "job_description": "x" * 250},
        ]
        result = compare_jobs(jobs)
        assert result[0]["_score"]["total"] >= result[1]["_score"]["total"]

    def test_empty_list(self):
        """Empty input returns empty output."""
        assert compare_jobs([]) == []

    def test_preserves_job_data(self):
        """Original job keys are preserved in output."""
        jobs = [{"id": 42, "location": "Zurich"}]
        result = compare_jobs(jobs)
        assert result[0]["id"] == 42
        assert "_score" in result[0]


# ---------------------------------------------------------------------------
# Route tests (smoke)
# ---------------------------------------------------------------------------

class TestCompareRoute:
    def test_compare_empty_state(self, client):
        """GET /compare with no ids returns 200 with empty state."""
        resp = client.get("/compare")
        assert resp.status_code == 200
        assert b"No jobs selected" in resp.data

    def test_compare_with_nonexistent_ids(self, client):
        """GET /compare?ids=999999 returns 200 (graceful handling)."""
        resp = client.get("/compare?ids=999999")
        assert resp.status_code == 200

    def test_compare_too_many_ids_capped(self, client):
        """More than 4 IDs are silently capped."""
        resp = client.get("/compare?ids=1,2,3,4,5,6")
        assert resp.status_code == 200


class TestTrackerRoute:
    def test_tracker_returns_200(self, client):
        """GET /tracker returns 200."""
        resp = client.get("/tracker")
        assert resp.status_code == 200
        assert b"My Job Tracker" in resp.data
