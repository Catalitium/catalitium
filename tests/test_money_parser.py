"""Tests for salary parsing edge cases used by CARL B2B analytics."""

from __future__ import annotations

import pytest

from app.models.money import parse_money_numbers, parse_salary_range_string


class TestParseMoneyNumbers:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("120,000.00", [120000]),
            ("120.000,50", [120000]),
            ("85k", [85000]),
            ("1.5k", [1500]),
            ("USD 100,000 - 140,000", [100000, 140000]),
        ],
    )
    def test_parses_standard_formats(self, raw, expected):
        assert parse_money_numbers(raw) == expected

    @pytest.mark.parametrize("raw", ["NULL", "null", "NA", "n/a", ""])
    def test_ignores_null_tokens(self, raw):
        assert parse_money_numbers(raw) == []


class TestParseSalaryRangeString:
    @pytest.mark.parametrize("raw", ["NULL", "null", "NA", "n/a", ""])
    def test_returns_none_for_null_tokens(self, raw):
        assert parse_salary_range_string(raw) is None

    def test_parses_decimal_currency_range(self):
        # Regression for decimal values accidentally inflated by 100x.
        assert parse_salary_range_string("USD 120,000.00 - 140,000.00") == 130000.0

    def test_hourly_suffix_is_annualized(self):
        assert parse_salary_range_string("US$60-80/hora") == 145600.0

    def test_hourly_single_value_is_annualized(self):
        assert parse_salary_range_string("USD 75 /hr") == 156000.0

    def test_yearly_suffix_not_annualized_again(self):
        assert parse_salary_range_string("USD 120000 /yr") == 120000.0
