"""Single Carl test module: B2C gate, Carl4B2B HTTP/API, Brave helpers, ghost score, salary drift.

Prefer extending ``tests/local_smoke.py`` (gitignored) for ad-hoc checks without growing this file.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from unittest import mock

import pytest

import app.controllers.carl as c4b_mod
from app.controllers.carl import (
    DEFAULT_MIN_SAMPLES,
    compute_ghost_score,
    compute_repost_index,
    compute_salary_drift,
    compute_sample_median_age_days,
    ghost_label,
    has_salary_signal,
    parse_posting_age_days,
)
from app.models.catalog import Job

# ---------------------------------------------------------------------------
# B2C /carl individuals gate
# ---------------------------------------------------------------------------


@pytest.fixture()
def carl_logged_in_client(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "00000000-0000-4000-8000-00000000c4rl",
            "email": "carl-individuals-gate@example.invalid",
        }
    return client


def test_carl_logged_in_returns_individuals_gate_markup(carl_logged_in_client):
    r = carl_logged_in_client.get("/carl")
    assert r.status_code == 200, r.get_data(as_text=True)[:500]
    html = r.get_data(as_text=True)
    assert 'id="carl-shell"' in html
    assert 'id="btn-select-individual"' in html
    assert 'id="carl-persona-gate"' in html
    assert 'id="carl-individuals-workspace"' in html
    assert 'type="button"' in html and "btn-select-individual" in html


def test_carl_individuals_inline_gate_wire_present_and_orders_elements(carl_logged_in_client):
    r = carl_logged_in_client.get("/carl")
    html = r.get_data(as_text=True)
    assert 'data-carl-gate-wire="1"' in html
    assert 'getElementById("btn-select-individual")' in html
    assert 'getElementById("carl-persona-gate")' in html
    assert 'getElementById("carl-individuals-workspace")' in html
    assert "addEventListener" in html and "click" in html
    assert 'classList.add("hidden")' in html or "classList.add('hidden')" in html
    assert "classList.remove(" in html and "hidden" in html

    idx_btn = html.index('id="btn-select-individual"')
    idx_wire = html.index("data-carl-gate-wire")
    idx_workspace = html.index('id="carl-individuals-workspace"')
    assert idx_btn < idx_workspace < idx_wire


def test_carl_guest_sees_individuals_gate(app):
    guest = app.test_client()
    r = guest.get("/carl", follow_redirects=False)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="btn-select-individual"' in html
    assert 'id="carl-persona-gate"' in html
    assert 'id="carl-guest-banner"' in html


def test_carl_menu_query_shows_persona_page(carl_logged_in_client):
    r = carl_logged_in_client.get("/carl?menu=1")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="carl-persona-gate"' in html
    assert 'id="btn-select-individual"' in html


def test_carl_js_linked_and_upload_form_no_fullpage_analyze(carl_logged_in_client):
    r = carl_logged_in_client.get("/carl")
    html = r.get_data(as_text=True)
    assert re.search(r'<script[^>]+src=["\'][^"\']*js/carl\.js', html) is not None
    assert 'id="carl-upload-form"' in html
    assert 'method="post"' in html
    assert 'id="carl-upload-btn"' in html and 'type="button"' in html
    assert "onsubmit=" in html


# ---------------------------------------------------------------------------
# Carl4B2B HTTP + market map
# ---------------------------------------------------------------------------


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


def test_carl4b2b_guest_get_ok(carl4b2b_client):
    r = carl4b2b_client.get("/carl/b2b", follow_redirects=False)
    assert r.status_code == 200
    assert b"carl4b2b-guest-banner" in r.data
    assert b"carl4b2b-market-form" in r.data


def test_carl4b2b_analyze_guest_needs_csrf(carl4b2b_client):
    r = carl4b2b_client.post(
        "/carl/b2b/analyze",
        json={"business_url": "https://example.com"},
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert r.get_json().get("code") == "invalid_csrf"


def test_carl4b2b_url_hints_empty(carl4b2b_client):
    r = carl4b2b_client.get("/carl/b2b/url-hints")
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("ok") is True
    assert (body.get("data") or {}).get("hints") is None


def test_carl4b2b_url_hints_stubbed(carl4b2b_client, monkeypatch):
    def fake_lookup(_url):
        return {"industry": "Software", "region": "EU", "comp_name": "Example Co"}

    monkeypatch.setattr(c4b_mod, "lookup_company_directory_hints", fake_lookup)
    r = carl4b2b_client.get("/carl/b2b/url-hints?url=https://careers.example.com")
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("ok") is True
    hints = (body.get("data") or {}).get("hints") or {}
    assert hints.get("comp_name") == "Example Co"


def test_carl4b2b_analyze_guest_quota(carl4b2b_client, monkeypatch):
    from app.config import CARL4B2B_GUEST_ANALYZE_LIMIT

    _stub_jobs(monkeypatch)
    page = carl4b2b_client.get("/carl/b2b")
    csrf = _csrf_from_b2b_page(page.get_data(as_text=True))
    payload = {"business_url": "https://example.com/careers"}
    headers = {"X-CSRF-Token": csrf, "Content-Type": "application/json"}
    for i in range(CARL4B2B_GUEST_ANALYZE_LIMIT):
        r = carl4b2b_client.post("/carl/b2b/analyze", json=payload, headers=headers)
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json().get("data") or {}
        assert data.get("guest_analyzes_remaining") == CARL4B2B_GUEST_ANALYZE_LIMIT - i - 1
    r = carl4b2b_client.post("/carl/b2b/analyze", json=payload, headers=headers)
    assert r.status_code == 403
    assert r.get_json().get("code") == "signup_required"


def test_carl4b2b_brave_allows_guest_after_analyze(carl4b2b_client, monkeypatch):
    _stub_jobs(monkeypatch)

    def fake_brave(_query):
        return [{"title": "T", "url": "https://example.invalid", "snippet": "S"}]

    monkeypatch.setattr(c4b_mod, "fetch_brave_context", fake_brave)
    page = carl4b2b_client.get("/carl/b2b")
    csrf = _csrf_from_b2b_page(page.get_data(as_text=True))
    ar = carl4b2b_client.post(
        "/carl/b2b/analyze",
        json={"business_url": "https://example.com/careers"},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert ar.status_code == 200
    br = carl4b2b_client.post(
        "/carl/b2b/brave/context",
        json={"context_type": "company"},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert br.status_code == 200
    body = br.get_json()
    assert body.get("ok") is True


def test_carl4b2b_brave_rejects_guest_without_analyze(carl4b2b_client):
    page = carl4b2b_client.get("/carl/b2b")
    csrf = _csrf_from_b2b_page(page.get_data(as_text=True))
    br = carl4b2b_client.post(
        "/carl/b2b/brave/context",
        json={"context_type": "company"},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert br.status_code == 401
    assert br.get_json().get("code") == "login_required"


def test_carl4b2b_get_ok_when_logged_in(carl4b2b_client):
    _b2b_login(carl4b2b_client)
    r = carl4b2b_client.get("/carl/b2b")
    assert r.status_code == 200
    data = r.data
    assert b"carl4b2b-market-form" in data
    assert b"btn-carl4b2b-new-map" in data
    assert b"menu=1" in data
    assert b"carl4b2b-guest-banner" not in data


def test_carl4b2b_analyze_manual_derives_market_company_when_missing(carl4b2b_client, monkeypatch):
    _stub_jobs(monkeypatch)
    _b2b_login(carl4b2b_client)
    page = carl4b2b_client.get("/carl/b2b")
    csrf = _csrf_from_b2b_page(page.get_data(as_text=True))
    r = carl4b2b_client.post(
        "/carl/b2b/analyze",
        json={"title": "Python engineer", "country": "Switzerland", "market_company": ""},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    mm = (r.get_json().get("data") or {}).get("analysis", {}).get("marketMeta") or {}
    assert mm.get("market_company") == "Python engineer"


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
        json={
            "title": "Python engineer",
            "country": "Switzerland",
            "market_company": "Acme",
            "business_url": "ftp://example.com",
        },
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
        json={
            "title": "Python engineer",
            "country": "Switzerland",
            "market_company": "Contoso",
        },
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


def test_carl4b2b_analyze_bare_host_url(carl4b2b_client, monkeypatch):
    _stub_jobs(monkeypatch)
    _b2b_login(carl4b2b_client)
    page = carl4b2b_client.get("/carl/b2b")
    csrf = _csrf_from_b2b_page(page.get_data(as_text=True))
    r = carl4b2b_client.post(
        "/carl/b2b/analyze",
        json={"business_url": "catalitium.com"},
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.get_json().get("ok") is True


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


def test_b2c_carl_guest_surface_ok(app):
    c = app.test_client()
    r = c.get("/carl", follow_redirects=False)
    assert r.status_code == 200


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
    cs = a.get("companies_summary") or {}
    assert "total_matched" in cs and "sample_rows" in cs
    assert "match_rate_pct" in cs
    assert "median_page_score" in cs
    assert "context_ribbon" in cs and cs["context_ribbon"]
    assert "spotlight_more_count" in cs
    se = a.get("spotlight_employers")
    assert isinstance(se, list)
    assert len(se) <= 3
    snap = c4b_mod._chat_snapshot_from_analysis(a)
    assert "directorySpotlight" in snap


# ---------------------------------------------------------------------------
# Brave query + fetch (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ctx,payload,needles",
    [
        ("company", {"company": "OpenAI"}, ('"OpenAI"', "hiring news")),
        ("role_market", {"title": "Data Analyst", "country": "UK"}, ('"Data Analyst"', "hiring market", "UK")),
        ("competitor", {"top_hirers": ["A", "B", "C", "D"]}, ('"A"', '"B"', '"C"')),
    ],
)
def test_build_brave_query_contains_needles(ctx, payload, needles):
    q = c4b_mod.build_brave_query(ctx, payload)
    for n in needles:
        assert n in q


def test_build_brave_query_empty_when_missing_company():
    assert c4b_mod.build_brave_query("company", {"company": ""}) == ""


def test_fetch_brave_context_happy_path_cached():
    c4b_mod.BRAVE_CACHE._store.clear()
    payload = {
        "web": {
            "results": [
                {
                    "title": "OpenAI is hiring",
                    "url": "https://example.com/x",
                    "description": "posted roles",
                }
            ]
        }
    }
    resp = mock.MagicMock()
    resp.status = 200
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__ = mock.MagicMock(return_value=resp)
    resp.__exit__ = mock.MagicMock(return_value=False)
    with mock.patch.object(c4b_mod, "urlopen", return_value=resp) as mocked:
        out = c4b_mod.fetch_brave_context("q", api_key="k")
        assert isinstance(out, list) and len(out) == 1
        c4b_mod.fetch_brave_context("q", api_key="k")
        assert mocked.call_count == 1


# ---------------------------------------------------------------------------
# Ghost score + salary drift (numeric core)
# ---------------------------------------------------------------------------

NOW_GHOST = datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc)


def test_parse_posting_age_days_iso():
    assert parse_posting_age_days("2026-04-10", now=NOW_GHOST) == 12
    assert parse_posting_age_days("not-a-date", now=NOW_GHOST) is None


@pytest.mark.parametrize("score,expected", [(0, "Active"), (25, "Uncertain"), (50, "Low hiring signal")])
def test_ghost_label_edges(score, expected):
    assert ghost_label(score) == expected


def test_has_salary_signal_detects():
    assert has_salary_signal({"job_salary_range": "USD 120,000"}) is True
    assert has_salary_signal({"job_salary_range": "N/A"}) is False


def test_compute_ghost_score_fresh_with_salary():
    row = {
        "company_name": "Acme",
        "job_title_norm": "Data Engineer",
        "date": "2026-04-20",
        "job_salary_range": "USD 120,000 - 140,000",
    }
    idx = compute_repost_index([row])
    result = compute_ghost_score(row, idx, now=NOW_GHOST)
    assert result["score"] == 0
    assert result["label"] == "Active"


NOW_SD = datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc)


def _sd_row(age_days: int, salary: str) -> dict:
    dt = NOW_SD.date().fromordinal(NOW_SD.date().toordinal() - age_days)
    return {"date": dt.isoformat(), "job_salary_range": salary}


def test_salary_drift_insufficient_gate():
    r = compute_salary_drift([], now=NOW_SD)
    assert r["status"] == "insufficient_data"
    assert r["sample_size"] == 0
    assert r["min_required"] == DEFAULT_MIN_SAMPLES


def test_salary_drift_flat_ok():
    rows = [_sd_row(i, "USD 100000") for i in range(1, 11)]
    r = compute_salary_drift(rows, now=NOW_SD)
    assert r["status"] == "ok"
    assert r["direction"] == "flat"
    assert r["delta_pct"] == 0.0
