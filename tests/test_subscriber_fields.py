"""Unit tests for subscriber digest field sanitization."""

from app.subscriber_fields import (
    sanitize_search_country,
    sanitize_search_salary_band,
    sanitize_search_title,
    sanitize_subscriber_search_fields,
)


def test_title_strips_bot_gibberish():
    assert sanitize_search_title("djwmwjix") == ""
    assert sanitize_search_title("kgzsissj") == ""
    # Multi-word titles must survive (spacing bypasses single-token gibberish rules).
    human = sanitize_search_title("Regional Sales Manager")
    assert human and " " in human
    # Short tokens skip the single-token gibberish filter (synonym expansion may apply).
    assert sanitize_search_title("foo") == "foo"


def test_country_iso_or_city_hint():
    assert sanitize_search_country("Germany") == "DE"
    assert sanitize_search_country("CH") == "CH"
    assert sanitize_search_country("iuztwzvv") == ""
    assert sanitize_search_country("Zurich") == "CH"


def test_salary_requires_signal():
    assert sanitize_search_salary_band("uyqfiiox") == ""
    assert sanitize_search_salary_band("CHF 120-160k") == "CHF 120-160k"
    assert sanitize_search_salary_band("market-research-r05") == "market-research-r05"


def test_tuple_helper():
    t, c, s = sanitize_subscriber_search_fields("djwmwjix", "iuztwzvv", "uyqfiiox")
    assert (t, c, s) == ("", "", "")
