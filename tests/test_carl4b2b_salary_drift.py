"""Tests for CARL B2B Salary Drift.

Covers the insufficient-data gate, the adaptive halves split, direction
label thresholds, and robustness against unparseable / NULL / hourly
salary tokens.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.controllers.carl4b2b_drift import (
    DEFAULT_MIN_SAMPLES,
    compute_salary_drift,
)


NOW = datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc)


def _row(age_days: int, salary: str) -> dict:
    # Build a row dated `age_days` before NOW with the given salary string.
    dt = NOW.date().fromordinal(NOW.date().toordinal() - age_days)
    return {
        "date": dt.isoformat(),
        "job_salary_range": salary,
    }


class TestInsufficientDataGate:
    def test_empty_rows_is_insufficient(self):
        r = compute_salary_drift([], now=NOW)
        assert r["status"] == "insufficient_data"
        assert r["sample_size"] == 0
        assert r["min_required"] == DEFAULT_MIN_SAMPLES

    def test_below_gate_is_insufficient(self):
        rows = [_row(i * 3, "USD 100000") for i in range(DEFAULT_MIN_SAMPLES - 1)]
        r = compute_salary_drift(rows, now=NOW)
        assert r["status"] == "insufficient_data"
        assert r["sample_size"] == DEFAULT_MIN_SAMPLES - 1

    def test_custom_min_samples(self):
        rows = [_row(i * 2, "USD 90000") for i in range(5)]
        r = compute_salary_drift(rows, now=NOW, min_samples=6)
        assert r["status"] == "insufficient_data"
        r2 = compute_salary_drift(rows, now=NOW, min_samples=3)
        assert r2["status"] == "ok"

    def test_rows_with_unparseable_salary_excluded(self):
        # 9 parseable + 3 junk = 9 usable, default gate 10 -> insufficient.
        rows = [_row(i, "USD 100000") for i in range(9)] + [
            _row(1, "NULL"),
            _row(2, "competitive"),
            _row(3, "N/A"),
        ]
        r = compute_salary_drift(rows, now=NOW)
        assert r["status"] == "insufficient_data"
        assert r["sample_size"] == 9

    def test_rows_with_unparseable_date_excluded(self):
        rows = [_row(i, "USD 100000") for i in range(9)] + [
            {"date": "garbage", "job_salary_range": "USD 100000"},
            {"date": None, "job_salary_range": "USD 100000"},
        ]
        r = compute_salary_drift(rows, now=NOW)
        assert r["status"] == "insufficient_data"
        assert r["sample_size"] == 9


class TestDirectionAndDelta:
    def test_flat_within_threshold(self):
        # newer half 100k, older half 100k -> 0%
        rows = [_row(i, "USD 100000") for i in range(1, 11)]
        r = compute_salary_drift(rows, now=NOW)
        assert r["status"] == "ok"
        assert r["direction"] == "flat"
        assert r["direction_label"] == "Stable"
        assert r["delta_pct"] == 0.0

    def test_trending_up(self):
        # Newer half (younger ages 1-10): 120k. Older half (11-20): 100k. +20%.
        rows = [_row(i, "USD 120000") for i in range(1, 11)]
        rows += [_row(i, "USD 100000") for i in range(11, 21)]
        r = compute_salary_drift(rows, now=NOW)
        assert r["status"] == "ok"
        assert r["direction"] == "up"
        assert r["direction_label"] == "Trending up"
        assert r["delta_pct"] == 20.0
        assert r["delta_abs"] == 20000
        assert r["sample_size"] == 20

    def test_trending_down(self):
        rows = [_row(i, "USD 80000") for i in range(1, 11)]
        rows += [_row(i, "USD 100000") for i in range(11, 21)]
        r = compute_salary_drift(rows, now=NOW)
        assert r["direction"] == "down"
        assert r["direction_label"] == "Trending down"
        assert r["delta_pct"] == -20.0

    def test_just_below_up_threshold_is_stable(self):
        # +4%: should be Stable not Trending up.
        rows = [_row(i, "USD 104000") for i in range(1, 11)]
        rows += [_row(i, "USD 100000") for i in range(11, 21)]
        r = compute_salary_drift(rows, now=NOW)
        assert r["direction"] == "flat"

    def test_exactly_at_up_threshold_is_up(self):
        rows = [_row(i, "USD 105000") for i in range(1, 11)]
        rows += [_row(i, "USD 100000") for i in range(11, 21)]
        r = compute_salary_drift(rows, now=NOW)
        assert r["direction"] == "up"

    def test_halves_are_disjoint_age_ranges(self):
        rows = [_row(i, "USD 110000") for i in range(1, 11)]
        rows += [_row(i, "USD 100000") for i in range(11, 21)]
        r = compute_salary_drift(rows, now=NOW)
        assert r["newer_half"]["age_max"] <= r["older_half"]["age_min"]
        assert r["newer_half"]["count"] == 10
        assert r["older_half"]["count"] == 10

    def test_odd_sample_puts_middle_in_older_half(self):
        rows = [_row(i, "USD 100000") for i in range(1, 12)]  # 11 rows
        r = compute_salary_drift(rows, now=NOW)
        assert r["sample_size"] == 11
        assert r["newer_half"]["count"] == 5
        assert r["older_half"]["count"] == 6


class TestHourlyAnnualization:
    def test_hourly_rates_are_annualized_and_comparable(self):
        # Mix: newer halves hourly, older halves yearly; parser normalizes to annual.
        rows = []
        rows += [_row(i, "USD 60 /hr") for i in range(1, 11)]   # 60*2080 = 124800
        rows += [_row(i, "USD 100000") for i in range(11, 21)]  # 100000
        r = compute_salary_drift(rows, now=NOW)
        assert r["status"] == "ok"
        assert r["newer_half"]["median_salary"] == 124800
        assert r["older_half"]["median_salary"] == 100000
        assert r["direction"] == "up"


class TestPayloadShape:
    def test_ok_payload_has_expected_keys(self):
        rows = [_row(i, "USD 100000") for i in range(1, 11)]
        r = compute_salary_drift(rows, now=NOW)
        for key in ("status", "sample_size", "min_required", "direction",
                    "direction_label", "delta_abs", "delta_pct",
                    "newer_half", "older_half", "note"):
            assert key in r, f"missing {key}"
        for key in ("count", "median_salary", "age_min", "age_max"):
            assert key in r["newer_half"], f"newer missing {key}"
            assert key in r["older_half"], f"older missing {key}"

    def test_insufficient_payload_has_expected_keys(self):
        r = compute_salary_drift([], now=NOW)
        for key in ("status", "sample_size", "min_required", "note"):
            assert key in r
