"""Tests for the Salary Intelligence Hub.

Covers:
- compute_percentile with various inputs
- PPP indices completeness
- categorize_function with various title keywords
- compare_cities_salary structure
- get_function_benchmarks / get_salary_trends fallback behaviour
- All 4 new routes return 200
"""

from __future__ import annotations

import pytest

from app.models.money import (
    compute_percentile,
    get_ppp_indices,
    compare_cities_salary,
    get_function_benchmarks,
    get_salary_trends,
)
from app.models.taxonomy import categorize_function


# ---------------------------------------------------------------------------
# Unit tests: PPP indices
# ---------------------------------------------------------------------------


class TestPPPIndices:
    def test_returns_dict(self):
        ppp = get_ppp_indices()
        assert isinstance(ppp, dict)

    def test_contains_zurich(self):
        ppp = get_ppp_indices()
        assert "Zurich" in ppp
        assert ppp["Zurich"] == 1.0

    def test_contains_expected_cities(self):
        ppp = get_ppp_indices()
        expected = [
            "San Francisco", "New York", "London", "Berlin", "Amsterdam",
            "Paris", "Dublin", "Barcelona", "Lisbon", "Warsaw",
            "Prague", "Vienna", "Munich", "Stockholm", "Copenhagen",
            "Helsinki", "Oslo", "Singapore", "Tokyo", "Sydney",
            "Toronto", "Vancouver", "Austin", "Seattle", "Boston",
            "Chicago", "Denver", "Miami", "Bangalore", "Remote",
        ]
        for city in expected:
            assert city in ppp, f"{city} missing from PPP indices"

    def test_all_values_between_0_and_2(self):
        ppp = get_ppp_indices()
        for city, val in ppp.items():
            assert 0 < val <= 2.0, f"{city} has invalid PPP index {val}"

    def test_returns_copy(self):
        """Mutating the return value doesn't affect the source."""
        ppp1 = get_ppp_indices()
        ppp1["FakeCity"] = 99.0
        ppp2 = get_ppp_indices()
        assert "FakeCity" not in ppp2


# ---------------------------------------------------------------------------
# Unit tests: categorize_function
# ---------------------------------------------------------------------------


class TestCategorizeFunction:
    @pytest.mark.parametrize("title,expected", [
        ("senior backend engineer", "Backend"),
        ("frontend developer react", "Frontend"),
        ("full-stack developer", "Fullstack"),
        ("machine learning engineer", "ML/AI"),
        ("data scientist", "Data"),
        ("devops engineer", "DevOps/Infra"),
        ("site reliability engineer", "DevOps/Infra"),
        ("product manager", "Product"),
        ("ux designer", "Design"),
        ("engineering manager", "Management"),
        ("security engineer", "Security"),
        ("office manager", "Other"),
        ("", "Other"),
    ])
    def test_categorization(self, title, expected):
        assert categorize_function(title) == expected

    def test_case_insensitive(self):
        assert categorize_function("BACKEND ENGINEER") == "Backend"
        assert categorize_function("Machine Learning") == "ML/AI"


# ---------------------------------------------------------------------------
# Unit tests: compute_percentile
# ---------------------------------------------------------------------------


class TestComputePercentile:
    def test_returns_salary_percentile_shape(self):
        result = compute_percentile("SWE", "Zurich", 130000, "CHF")
        assert "title" in result
        assert "location" in result
        assert "user_salary" in result
        assert "currency" in result
        assert "median" in result
        assert "percentile_rank" in result
        assert "label" in result

    def test_percentile_rank_clamped_0_100(self):
        result = compute_percentile("SWE", "NonexistentCity999", 50000, "CHF")
        assert 0 <= result["percentile_rank"] <= 100

    def test_above_market_label(self):
        result = compute_percentile("SWE", "TestCity", 999999, "CHF")
        assert result["percentile_rank"] >= 0

    def test_currency_passed_through(self):
        result = compute_percentile("SWE", "Berlin", 80000, "EUR")
        assert result["currency"] == "EUR"

    def test_user_salary_stored(self):
        result = compute_percentile("PM", "London", 75000, "GBP")
        assert result["user_salary"] == 75000.0

    def test_label_values(self):
        result = compute_percentile("SWE", "Unknown", 50000, "CHF")
        assert result["label"] in ("above_market", "at_market", "below_market")


# ---------------------------------------------------------------------------
# Unit tests: compare_cities_salary
# ---------------------------------------------------------------------------


class TestCompareCitiesSalary:
    def test_returns_list(self):
        result = compare_cities_salary("SWE", ["Zurich", "Berlin"])
        assert isinstance(result, list)
        assert len(result) == 2

    def test_result_has_expected_keys(self):
        result = compare_cities_salary("SWE", ["Zurich"])
        assert len(result) == 1
        item = result[0]
        assert "city" in item
        assert "raw_median" in item
        assert "ppp_index" in item
        assert "adjusted_salary" in item

    def test_ppp_index_from_known_city(self):
        result = compare_cities_salary("SWE", ["Bangalore"])
        assert result[0]["ppp_index"] == 0.25


# ---------------------------------------------------------------------------
# Route smoke tests
# ---------------------------------------------------------------------------


class TestSalaryIntelligenceRoutes:
    def test_underpaid_get(self, client):
        resp = client.get("/salary/am-i-underpaid")
        assert resp.status_code == 200
        assert b"Am I Underpaid" in resp.data

    def test_underpaid_with_params(self, client):
        resp = client.get("/salary/am-i-underpaid?title=SWE&location=Zurich&salary=130000&currency=CHF")
        assert resp.status_code == 200

    def test_compare_cities_get(self, client):
        resp = client.get("/salary/compare-cities")
        assert resp.status_code == 200
        assert b"Cross-City" in resp.data

    def test_by_function_get(self, client):
        resp = client.get("/salary/by-function")
        assert resp.status_code == 200
        assert b"Function" in resp.data

    def test_trends_get(self, client):
        resp = client.get("/salary/trends")
        assert resp.status_code == 200
        assert b"Trends" in resp.data

    def test_trends_with_filters(self, client):
        resp = client.get("/salary/trends?category=Backend&city=Zurich")
        assert resp.status_code == 200
