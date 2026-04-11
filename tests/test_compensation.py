"""Tests for the compensation intelligence layer.

Covers:
- Confidence scoring with various inputs
- Source label assignment
- Methodology route returns 200
"""

from __future__ import annotations

import pytest

from app.models.compensation import (
    compute_compensation_confidence,
    confidence_color,
    source_label,
)


# ---------------------------------------------------------------------------
# Unit tests: compute_compensation_confidence
# ---------------------------------------------------------------------------


class TestConfidenceScoring:
    """Confidence scoring with various input combinations."""

    def test_employer_salary_present_high_confidence(self):
        result = compute_compensation_confidence(
            {
                "salary": "CHF 120k-150k",
                "job_salary": 135000,
                "salary_min": 108000,
                "salary_max": 162000,
                "median_salary_currency": "CHF",
            },
            (130000.0, "CHF"),
            has_crowd_data=True,
            ref_match_level="city",
        )
        assert result["source"] == "employer"
        assert result["confidence"] >= 70
        assert result["median"] == 130000.0
        assert result["currency"] == "CHF"
        assert result["range_low"] == 108000
        assert result["range_high"] == 162000
        assert "methodology_url" in result

    def test_estimated_city_level(self):
        result = compute_compensation_confidence(
            {
                "salary": "",
                "job_salary": None,
                "salary_min": 96000,
                "salary_max": 144000,
                "median_salary_currency": "EUR",
            },
            (120000.0, "EUR"),
            has_crowd_data=False,
            ref_match_level="city",
        )
        assert result["source"] == "estimated"
        # city match: +30 ref + +10 specificity = 40
        assert result["confidence"] == 40
        assert result["median"] == 120000.0

    def test_estimated_country_level(self):
        result = compute_compensation_confidence(
            {
                "salary": "",
                "job_salary": None,
                "salary_min": 80000,
                "salary_max": 120000,
                "median_salary_currency": "EUR",
            },
            (100000.0, "EUR"),
            has_crowd_data=False,
            ref_match_level="country",
        )
        assert result["source"] == "estimated"
        # country match: +15 ref, no specificity bonus = 15
        assert result["confidence"] == 15

    def test_estimated_fallback_level(self):
        result = compute_compensation_confidence(
            {
                "salary": "",
                "job_salary": None,
                "salary_min": 70000,
                "salary_max": 110000,
                "median_salary_currency": "USD",
            },
            (90000.0, "USD"),
            has_crowd_data=False,
            ref_match_level="fallback",
        )
        assert result["source"] == "estimated"
        assert result["confidence"] == 5

    def test_crowd_data_only(self):
        result = compute_compensation_confidence(
            {
                "salary": "",
                "job_salary": None,
                "salary_min": None,
                "salary_max": None,
                "median_salary_currency": None,
            },
            None,
            has_crowd_data=True,
            ref_match_level="none",
        )
        assert result["source"] == "crowd"
        assert result["confidence"] == 15

    def test_no_data_unavailable(self):
        result = compute_compensation_confidence(
            {
                "salary": "",
                "job_salary": None,
                "salary_min": None,
                "salary_max": None,
                "median_salary_currency": None,
            },
            None,
            has_crowd_data=False,
            ref_match_level="none",
        )
        assert result["source"] == "unavailable"
        assert result["confidence"] == 0
        assert result["median"] is None
        assert result["range_low"] is None
        assert result["range_high"] is None

    def test_employer_plus_crowd_plus_city(self):
        """Maximum confidence: employer salary + city ref + crowd data."""
        result = compute_compensation_confidence(
            {
                "salary": "120k-150k CHF",
                "job_salary": 135000,
                "salary_min": 108000,
                "salary_max": 162000,
                "median_salary_currency": "CHF",
            },
            (130000.0, "CHF"),
            has_crowd_data=True,
            ref_match_level="city",
        )
        # employer: +40, city ref: +30, crowd: +15, city specificity: +10 = 95
        assert result["confidence"] == 95

    def test_confidence_clamped_to_100(self):
        """Score never exceeds 100."""
        result = compute_compensation_confidence(
            {
                "salary": "120k-150k",
                "job_salary": 135000,
                "salary_min": 108000,
                "salary_max": 162000,
                "median_salary_currency": "CHF",
            },
            (130000.0, "CHF"),
            has_crowd_data=True,
            ref_match_level="city",
        )
        assert result["confidence"] <= 100

    def test_job_salary_int_counts_as_employer(self):
        """job_salary > 0 alone should count as employer data."""
        result = compute_compensation_confidence(
            {
                "salary": "",
                "job_salary": 100000,
                "salary_min": None,
                "salary_max": None,
                "median_salary_currency": None,
            },
            None,
            has_crowd_data=False,
            ref_match_level="none",
        )
        assert result["source"] == "employer"
        assert result["confidence"] == 40

    def test_methodology_url_default(self):
        result = compute_compensation_confidence(
            {"salary": "", "job_salary": None, "salary_min": None, "salary_max": None, "median_salary_currency": None},
            None,
        )
        assert result["methodology_url"] == "/compensation/methodology"

    def test_methodology_url_custom(self):
        result = compute_compensation_confidence(
            {"salary": "", "job_salary": None, "salary_min": None, "salary_max": None, "median_salary_currency": None},
            None,
            methodology_url="/custom/path",
        )
        assert result["methodology_url"] == "/custom/path"


# ---------------------------------------------------------------------------
# Unit tests: source_label and confidence_color
# ---------------------------------------------------------------------------


class TestSourceLabel:
    def test_employer(self):
        assert source_label("employer") == "Employer provided"

    def test_estimated(self):
        assert source_label("estimated") == "Estimated from market data"

    def test_crowd(self):
        assert source_label("crowd") == "Community reported"

    def test_unavailable(self):
        assert source_label("unavailable") == "Not available"

    def test_unknown_falls_back(self):
        assert source_label("something_else") == "Not available"


class TestConfidenceColor:
    def test_green(self):
        assert confidence_color(70) == "green"
        assert confidence_color(100) == "green"

    def test_amber(self):
        assert confidence_color(40) == "amber"
        assert confidence_color(69) == "amber"

    def test_gray(self):
        assert confidence_color(0) == "gray"
        assert confidence_color(39) == "gray"


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


class TestMethodologyRoute:
    def test_methodology_returns_200(self, client):
        resp = client.get("/compensation/methodology")
        assert resp.status_code == 200

    def test_methodology_contains_title(self, client):
        resp = client.get("/compensation/methodology")
        assert b"How We Estimate Salaries" in resp.data

    def test_methodology_contains_confidence_explanation(self, client):
        resp = client.get("/compensation/methodology")
        assert b"Confidence Scores" in resp.data
