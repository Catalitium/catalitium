"""Tests for CARL B2B Ghost Likelihood Score.

Covers age parsing, repost indexing, salary signal detection, overall score
computation across score bands, label mapping, and the exception fallback.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.controllers.carl4b2b_ghost import (
    compute_ghost_score,
    compute_repost_index,
    compute_sample_median_age_days,
    ghost_label,
    has_salary_signal,
    parse_posting_age_days,
)


NOW = datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc)


class TestParsePostingAgeDays:
    def test_datetime(self):
        posted = datetime(2026, 4, 10, tzinfo=timezone.utc)
        assert parse_posting_age_days(posted, now=NOW) == 12

    def test_date(self):
        assert parse_posting_age_days(date(2026, 4, 10), now=NOW) == 12

    def test_iso_date_string(self):
        assert parse_posting_age_days("2026-04-10", now=NOW) == 12

    def test_iso_datetime_string(self):
        assert parse_posting_age_days("2026-04-10T09:30:00", now=NOW) == 12

    def test_iso_datetime_with_z(self):
        assert parse_posting_age_days("2026-04-10T09:30:00Z", now=NOW) == 12

    @pytest.mark.parametrize("value", [None, "", "not-a-date", "2026/04/10"])
    def test_invalid_returns_none(self, value):
        assert parse_posting_age_days(value, now=NOW) is None

    def test_future_date_clamps_to_zero(self):
        assert parse_posting_age_days("2099-01-01", now=NOW) == 0


class TestComputeSampleMedianAgeDays:
    def test_empty_returns_none(self):
        assert compute_sample_median_age_days([], now=NOW) is None

    def test_below_min_parseable_returns_none(self):
        rows = [{"date": "2026-04-20"}, {"date": "2026-04-10"}]
        assert compute_sample_median_age_days(rows, now=NOW) is None

    def test_mixed_garbage_uses_only_parseable(self):
        rows = [
            {"date": "2026-04-20"},
            {"date": "not-a-date"},
            {"date": "2026-04-10"},
            {"date": None},
            {"date": "2026-03-20"},
        ]
        assert compute_sample_median_age_days(rows, now=NOW) == 12

    def test_odd_count(self):
        rows = [{"date": "2026-04-20"}, {"date": "2026-04-10"}, {"date": "2026-03-20"}]
        assert compute_sample_median_age_days(rows, now=NOW) == 12

    def test_even_count_rounds(self):
        rows = [
            {"date": "2026-04-21"},  # 1d
            {"date": "2026-04-18"},  # 4d
            {"date": "2026-04-15"},  # 7d
            {"date": "2026-04-12"},  # 10d
        ]
        assert compute_sample_median_age_days(rows, now=NOW) == 6


class TestComputeRepostIndex:
    def test_counts_case_insensitive(self):
        rows = [
            {"company_name": "Acme", "job_title_norm": "Data Engineer"},
            {"company_name": "ACME", "job_title_norm": "data engineer"},
            {"company_name": "acme", "job_title_norm": "DATA ENGINEER"},
            {"company_name": "Globex", "job_title_norm": "Data Engineer"},
        ]
        idx = compute_repost_index(rows)
        assert idx[("acme", "data engineer")] == 3
        assert idx[("globex", "data engineer")] == 1

    def test_skips_empty_keys(self):
        rows = [
            {"company_name": "", "job_title_norm": "Engineer"},
            {"company_name": "Acme", "job_title_norm": ""},
            {"company_name": "Acme", "job_title_norm": "Engineer"},
        ]
        idx = compute_repost_index(rows)
        assert idx == {("acme", "engineer"): 1}

    def test_falls_back_to_job_title(self):
        rows = [
            {"company_name": "Acme", "job_title": "Analyst"},
            {"company_name": "Acme", "job_title": "Analyst"},
        ]
        idx = compute_repost_index(rows)
        assert idx[("acme", "analyst")] == 2


class TestHasSalarySignal:
    @pytest.mark.parametrize("raw,expected", [
        ("USD 120,000 - 140,000", True),
        ("120000", True),
        ("85k", True),
        ("", False),
        (None, False),
        ("NULL", False),
        ("N/A", False),
        ("competitive", False),
    ])
    def test_detects_signal(self, raw, expected):
        assert has_salary_signal({"job_salary_range": raw}) is expected


class TestGhostLabel:
    @pytest.mark.parametrize("score,expected", [
        (0, "Active"),
        (24, "Active"),
        (25, "Uncertain"),
        (49, "Uncertain"),
        (50, "Low hiring signal"),
        (100, "Low hiring signal"),
    ])
    def test_band_edges(self, score, expected):
        assert ghost_label(score) == expected


class TestComputeGhostScore:
    def _row(self, **overrides):
        base = {
            "company_name": "Acme",
            "job_title_norm": "Data Engineer",
            "date": "2026-04-20",
            "job_salary_range": "USD 120,000 - 140,000",
        }
        base.update(overrides)
        return base

    def test_fresh_with_salary_is_active(self):
        row = self._row()
        idx = compute_repost_index([row])
        result = compute_ghost_score(row, idx, now=NOW)
        assert result["score"] == 0
        assert result["label"] == "Active"
        factor_keys = [f["key"] for f in result["factors"]]
        assert factor_keys == ["age", "repost", "salary", "velocity"]

    def test_stale_single_row_absolute_fallback_is_low(self):
        # Single row: no median available, absolute bands apply; >60d + no salary = Low.
        row = self._row(date="2026-01-01", job_salary_range="")
        idx = compute_repost_index([row])
        result = compute_ghost_score(row, idx, now=NOW)
        assert result["score"] >= 50
        assert result["label"] == "Low hiring signal"

    def test_outlier_stale_among_fresh_is_low(self):
        fresh_rows = [self._row(company_name=f"Co{i}", date="2026-04-20") for i in range(5)]
        stale = self._row(company_name="StaleCo", date="2026-01-01", job_salary_range="")
        rows = fresh_rows + [stale]
        idx = compute_repost_index(rows)
        median_age = compute_sample_median_age_days(rows, now=NOW)
        result = compute_ghost_score(
            stale, idx, sample_median_age_days=median_age, now=NOW
        )
        age = next(f for f in result["factors"] if f["key"] == "age")
        assert age["points"] == 40
        assert result["label"] == "Low hiring signal"

    def test_uniform_stale_is_typical_not_flagged(self):
        # Screenshot scenario: every row ~60 days old, no salary, no reposts.
        # Relative scoring must NOT produce a wall of 'Low hiring signal'.
        rows = [
            self._row(company_name=f"Co{i}", date="2026-02-21", job_salary_range="")
            for i in range(6)
        ]
        idx = compute_repost_index(rows)
        median_age = compute_sample_median_age_days(rows, now=NOW)
        result = compute_ghost_score(
            rows[0], idx, sample_median_age_days=median_age, now=NOW
        )
        age = next(f for f in result["factors"] if f["key"] == "age")
        assert age["points"] == 10
        assert result["label"] in {"Active", "Uncertain"}
        assert result["label"] != "Low hiring signal"

    def test_fresh_absolute_floor_wins_over_relative(self):
        # If a row is <=14d old, it gets 0 pts even in an all-fresh sample
        # where median is near zero.
        rows = [self._row(company_name=f"Co{i}", date="2026-04-21") for i in range(5)]
        idx = compute_repost_index(rows)
        median_age = compute_sample_median_age_days(rows, now=NOW)
        result = compute_ghost_score(
            rows[0], idx, sample_median_age_days=median_age, now=NOW
        )
        age = next(f for f in result["factors"] if f["key"] == "age")
        assert age["points"] == 0

    def test_repost_adds_points(self):
        row = self._row()
        idx = compute_repost_index([row, row])
        result = compute_ghost_score(row, idx, now=NOW)
        repost_factor = next(f for f in result["factors"] if f["key"] == "repost")
        assert repost_factor["points"] == 10

    def test_velocity_is_placeholder_zero(self):
        row = self._row()
        idx = compute_repost_index([row])
        result = compute_ghost_score(row, idx, now=NOW)
        velocity = next(f for f in result["factors"] if f["key"] == "velocity")
        assert velocity["points"] == 0
        assert "last_seen_at" in velocity["detail"]

    def test_score_is_clamped_to_0_100(self):
        row = self._row(date="2020-01-01", job_salary_range="")
        idx = compute_repost_index([row, row, row, row])
        result = compute_ghost_score(row, idx, now=NOW)
        assert 0 <= result["score"] <= 100

    def test_malformed_row_falls_back_to_uncertain(self):
        class Explosive(dict):
            def get(self, key, default=None):
                raise RuntimeError("boom")

        result = compute_ghost_score(Explosive(), {}, now=NOW)
        assert result["score"] == 50
        assert result["label"] == "Uncertain"
        assert result["factors"][0]["key"] == "error"
