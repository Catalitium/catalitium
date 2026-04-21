"""Carl4B2B routes and catalog-backed market map (parallel to B2C Carl)."""

from __future__ import annotations

import json
import re

import pytest

import app.controllers.carl4b2b as c4b_mod
from app.models.catalog import Job


@pytest.fixture()
def carl4b2b_client(app, monkeypatch):
    monkeypatch.setattr(c4b_mod, "upsert_profile_carl4b2b_analysis", lambda *a, **k: "ok")
    return app.test_client()


def _b2b_login(client, *, uid: str = "00000000-0000-4000-8000-000000000077") -> None:
    with client.session_transaction() as sess:
        sess["user"] = {"id": uid, "email": "carl4b2b-pytest@example.invalid"}


def _csrf_from_b2b_page(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m, "csrf_token missing on /carl/b2b"
    return m.group(1)


def _stub_jobs(monkeypatch):
    rows = [
        {
            "job_title": "Python Engineer",
            "company_name": "Acme Corp",
            "location": "Zurich",
            "city": "Zurich",
            "country": "CH",
            "link": "https://example.invalid/j/1",
        },
        {
            "job_title": "Python Developer",
            "company_name": "Acme Corp",
            "location": "Zurich",
            "city": "",
            "country": "CH",
            "link": "https://example.invalid/j/2",
        },
        {
            "job_title": "Data Scientist",
            "company_name": "Beta Ltd",
            "location": "Bern",
            "city": "",
            "country": "CH",
            "link": "https://example.invalid/j/3",
        },
    ]

    def fake_count(*_a, **_k):
        return 42

    def fake_search(*_a, limit=50, offset=0, **_k):
        return list(rows[: int(limit)])

    monkeypatch.setattr(Job, "count", staticmethod(fake_count))
    monkeypatch.setattr(Job, "search", staticmethod(fake_search))


def test_carl4b2b_guest_redirect(carl4b2b_client):
    r = carl4b2b_client.get("/carl/b2b", follow_redirects=False)
    assert r.status_code in (301, 302)


def test_carl4b2b_get_ok_when_logged_in(carl4b2b_client):
    _b2b_login(carl4b2b_client)
    r = carl4b2b_client.get("/carl/b2b")
    assert r.status_code == 200
    assert b"carl4b2b-market-form" in r.data
    assert b"btn-carl4b2b-new-map" in r.data
    assert b"menu=1" in r.data


def test_carl4b2b_analyze_requires_login(carl4b2b_client):
    r = carl4b2b_client.post("/carl/b2b/analyze", json={"business_url": "https://example.com"})
    assert r.status_code == 401


def test_carl4b2b_analyze_validation(carl4b2b_client):
    _b2b_login(carl4b2b_client)
    page = carl4b2b_client.get("/carl/b2b")
    csrf = _csrf_from_b2b_page(page.get_data(as_text=True))
    r = carl4b2b_client.post(
        "/carl/b2b/analyze",
        json={"business_url": ""},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert r.status_code == 400
    body = r.get_json()
    assert body.get("ok") is False
    assert body.get("code") == "invalid_input"


def test_carl4b2b_analyze_manual_ignores_bad_url(carl4b2b_client, monkeypatch):
    _stub_jobs(monkeypatch)
    _b2b_login(carl4b2b_client)
    page = carl4b2b_client.get("/carl/b2b")
    csrf = _csrf_from_b2b_page(page.get_data(as_text=True))
    r = carl4b2b_client.post(
        "/carl/b2b/analyze",
        json={"title": "Python engineer", "country": "Switzerland", "business_url": "ftp://example.com"},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    logs = " ".join((r.get_json().get("data") or {}).get("analysis", {}).get("terminalLogs") or [])
    assert "ignored" in logs.lower()
    assert ((r.get_json().get("data") or {}).get("source") or {}).get("inputType") == "manual"


def test_carl4b2b_analyze_manual_title_country(carl4b2b_client, monkeypatch):
    _stub_jobs(monkeypatch)
    _b2b_login(carl4b2b_client)
    page = carl4b2b_client.get("/carl/b2b")
    csrf = _csrf_from_b2b_page(page.get_data(as_text=True))
    r = carl4b2b_client.post(
        "/carl/b2b/analyze",
        json={"title": "Python engineer", "country": "Switzerland", "exclude_company": "Acme"},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    env = r.get_json()
    assert env.get("ok") is True
    data = env.get("data") or {}
    assert (data.get("source") or {}).get("inputType") == "manual"
    mm = (data.get("analysis") or {}).get("marketMeta") or {}
    assert mm.get("input_type") == "manual"
    assert mm.get("inferred_from_url") is False


def test_carl4b2b_analyze_happy_path_json(carl4b2b_client, monkeypatch):
    _stub_jobs(monkeypatch)
    _b2b_login(carl4b2b_client)
    page = carl4b2b_client.get("/carl/b2b")
    csrf = _csrf_from_b2b_page(page.get_data(as_text=True))
    r = carl4b2b_client.post(
        "/carl/b2b/analyze",
        json={"business_url": "https://example.com/careers"},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    env = r.get_json()
    assert env.get("ok") is True
    data = env.get("data") or {}
    analysis = data.get("analysis") or {}
    assert "overview" in analysis
    assert "terminalLogs" in analysis
    assert "chatContext" in analysis
    assert "marketMeta" in analysis
    assert analysis["marketMeta"].get("total_count") == 42
    matches = analysis.get("matches") or {}
    assert "jobs" in matches and "top_companies" in matches


def test_carl4b2b_chat_grounded_chip(carl4b2b_client, monkeypatch):
    _stub_jobs(monkeypatch)
    _b2b_login(carl4b2b_client)
    page = carl4b2b_client.get("/carl/b2b")
    csrf = _csrf_from_b2b_page(page.get_data(as_text=True))
    ar = carl4b2b_client.post(
        "/carl/b2b/analyze",
        json={"business_url": "https://example.ch/jobs"},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert ar.status_code == 200
    cr = carl4b2b_client.post(
        "/carl/b2b/chat",
        json={"prompt_id": 0},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert cr.status_code == 200
    out = cr.get_json()
    assert out.get("ok") is True
    assert (out.get("data") or {}).get("reply")


def test_b2c_carl_guest_unchanged(app):
    """Regression: B2C Carl surface not altered by B2B registration."""
    c = app.test_client()
    r = c.get("/carl", follow_redirects=False)
    assert r.status_code in (301, 302)


def test_is_carl4b2b_message_grounded_catalog_term():
    snap = {"suggestedPrompts": ["A"], "headline": "Hiring xxyz"}
    assert c4b_mod.is_carl4b2b_message_grounded("What does catalog coverage mean?", snap) is True


def test_build_market_map_smoke(monkeypatch):
    _stub_jobs(monkeypatch)
    a = c4b_mod.build_market_map_analysis(
        title_raw="python",
        country_raw="CH",
        exclude_company="",
        meta={},
    )
    assert a["overview"]["headline"]
    assert isinstance(a["terminalLogs"], list)
