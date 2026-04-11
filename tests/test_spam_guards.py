"""Tests for spam_guards helpers."""

from app.spam_guards import (
    disposable_email_domain,
    honeypot_triggered,
    prepare_contact_submission,
)


def test_honeypot_empty_ok():
    assert honeypot_triggered({}) is False
    assert honeypot_triggered({"hp_company_url": ""}) is False
    assert honeypot_triggered({"hp_company_url": "   "}) is False


def test_honeypot_non_empty():
    assert honeypot_triggered({"hp_company_url": "http://evil.com"}) is True


def test_disposable_domain():
    assert disposable_email_domain("a@mailinator.com") is True
    assert disposable_email_domain("a@sub.mailinator.com") is True
    assert disposable_email_domain("a@gmail.com") is False


def test_prepare_contact_accepts_normal():
    n, m = prepare_contact_submission("Ada", "Hello — we'd love to partner on salary data.")
    assert n == "Ada"
    assert "partner" in m


def test_prepare_contact_rejects_scriptish():
    assert prepare_contact_submission("Bob", "<script>alert(1)</script>") is None


def test_prepare_contact_rejects_link_dump():
    msg = " ".join(["https://example.com/x" for _ in range(8)])
    assert prepare_contact_submission("Spam", msg) is None


def test_prepare_contact_rejects_repetition():
    assert prepare_contact_submission("X", "a" * 30) is None
