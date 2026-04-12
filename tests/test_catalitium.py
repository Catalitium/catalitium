# ✓ Catalitium — consolidated automated checks (fast, env-aware, one file)
# =============================================================================
# Ship gate — single test module
# Run: pytest tests/   or   pytest tests/test_catalitium.py
# Live Carl + Postgres (opt-in): RUN_CARL_DB_INTEGRATION=1 and CARL_TEST_USER_ID
# =============================================================================
"""Release matrix: HTTP surfaces, API shape, security headers, Carl demo, pure units.

Stable by design: no dated marketing strings; Carl live check is env-gated at file tail.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict

import pytest

import app.factory as app_factory
from app.factory import safe_parse_search_params
from app.config import CARL_CHAT_MAX_REPLY_CHARS
from app.integrations.carl_mock_analysis import (
    generate_chat_reply,
    is_carl_message_grounded,
    normalize_carl_user_message,
)
from app.utils import (
    disposable_email_domain,
    honeypot_triggered,
    prepare_contact_submission,
    sanitize_search_country,
    sanitize_search_salary_band,
    sanitize_search_title,
    sanitize_subscriber_search_fields,
    slugify_job_title,
)

# -----------------------------------------------------------------------------


@pytest.fixture()
def carl_client(app, monkeypatch):
    """Carl routes: stub profile upsert (no DB write required for default tests)."""
    monkeypatch.setattr(app_factory, "upsert_profile_cv_extract", lambda *a, **k: "ok")
    return app.test_client()


def _carl_login(client, *, uid: str = "00000000-0000-4000-8000-000000000042") -> None:
    with client.session_transaction() as sess:
        sess["user"] = {"id": uid, "email": "carl-pytest@example.invalid"}


def _csrf_from_carl_page(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m, "csrf_token missing on /carl"
    return m.group(1)


# --- Subscriber fields (pure) -------------------------------------------------


def test_subscriber_title_strips_bot_gibberish():
    assert sanitize_search_title("djwmwjix") == ""
    assert sanitize_search_title("kgzsissj") == ""
    human = sanitize_search_title("Regional Sales Manager")
    assert human and " " in human
    assert sanitize_search_title("foo") == "foo"


def test_subscriber_country_iso_or_city_hint():
    assert sanitize_search_country("Germany") == "DE"
    assert sanitize_search_country("CH") == "CH"
    assert sanitize_search_country("iuztwzvv") == ""
    assert sanitize_search_country("Zurich") == "CH"


def test_subscriber_salary_requires_signal():
    assert sanitize_search_salary_band("uyqfiiox") == ""
    assert sanitize_search_salary_band("CHF 120-160k") == "CHF 120-160k"
    assert sanitize_search_salary_band("market-research-r05") == "market-research-r05"


def test_subscriber_tuple_helper():
    t, c, s = sanitize_subscriber_search_fields("djwmwjix", "iuztwzvv", "uyqfiiox")
    assert (t, c, s) == ("", "", "")


# --- Spam guards (pure) ------------------------------------------------------


def test_spam_honeypot_empty_ok():
    assert honeypot_triggered({}) is False
    assert honeypot_triggered({"hp_company_url": ""}) is False
    assert honeypot_triggered({"hp_company_url": "   "}) is False


def test_spam_honeypot_non_empty():
    assert honeypot_triggered({"hp_company_url": "http://evil.com"}) is True


def test_spam_disposable_domain():
    assert disposable_email_domain("a@mailinator.com") is True
    assert disposable_email_domain("a@sub.mailinator.com") is True
    assert disposable_email_domain("a@gmail.com") is False


def test_spam_prepare_contact_accepts_normal():
    n, m = prepare_contact_submission("Ada", "Hello — we'd love to partner on salary data.")
    assert n == "Ada"
    assert "partner" in m


def test_spam_prepare_contact_rejects_scriptish():
    assert prepare_contact_submission("Bob", "<script>alert(1)</script>") is None


def test_spam_prepare_contact_rejects_link_dump():
    msg = " ".join(["https://example.com/x" for _ in range(8)])
    assert prepare_contact_submission("Spam", msg) is None


def test_spam_prepare_contact_rejects_repetition():
    assert prepare_contact_submission("X", "a" * 30) is None


# --- Carl grounding (pure) ---------------------------------------------------


def _carl_snapshot() -> dict:
    return {
        "suggestedPrompts": [
            "Where should I add python, sql without keyword stuffing?",
            "Rewrite one experience block for hiring managers in 4 bullets.",
            "What metrics would make my impact undeniable on a first skim?",
        ],
        "missingKeywords": ["kubernetes", "leadership"],
        "matchedKeywords": ["python", "sql"],
        "topSkillNames": ["Python", "AWS"],
        "persona": "Backend Engineer",
        "level": "Senior",
        "headline": "Senior Backend Engineer profile with 55% ATS keyword coverage",
        "fileLabel": "resume.pdf",
    }


def test_carl_normalize_user_message_collapse_ws():
    assert normalize_carl_user_message("  a   b  ") == "a b"


def test_carl_grounding_prompt_id():
    snap = _carl_snapshot()
    assert is_carl_message_grounded("", snap, prompt_id=0) is True
    assert is_carl_message_grounded("", snap, prompt_id=2) is True
    assert is_carl_message_grounded("", snap, prompt_id=9) is False


def test_carl_grounding_exact_suggested_string():
    snap = _carl_snapshot()
    p0 = snap["suggestedPrompts"][0]
    assert is_carl_message_grounded(f"  {p0}  ", snap) is True


def test_carl_grounding_missing_keyword_substring():
    snap = _carl_snapshot()
    assert is_carl_message_grounded("How do I show kubernetes experience?", snap) is True


def test_carl_grounding_matched_keyword():
    snap = _carl_snapshot()
    assert is_carl_message_grounded("Is python enough for this role?", snap) is True


def test_carl_grounding_persona_level_file():
    snap = _carl_snapshot()
    assert is_carl_message_grounded("Does this read as Senior?", snap) is True
    assert is_carl_message_grounded("Backend Engineer narrative", snap) is True
    assert is_carl_message_grounded("Compare to resume.pdf", snap) is True


def test_carl_grounding_headline_token():
    snap = _carl_snapshot()
    assert is_carl_message_grounded("Tell me about keyword coverage on this pass", snap) is True


def test_carl_grounding_rejects_unrelated():
    snap = _carl_snapshot()
    assert is_carl_message_grounded("What is the weather in Paris tomorrow?", snap) is False


def test_carl_generate_reply_respects_max_length():
    snap = _carl_snapshot()
    ctx = {
        "summary": snap.get("summary", ""),
        "missingKeywords": snap["missingKeywords"],
        "persona": snap["persona"],
        "level": snap["level"],
        "headline": snap["headline"],
        "fileLabel": snap["fileLabel"],
        "topSkillNames": snap["topSkillNames"],
    }
    out = generate_chat_reply(snap["suggestedPrompts"][0], ctx)
    assert len(out) <= CARL_CHAT_MAX_REPLY_CHARS


@pytest.mark.parametrize(
    "msg,expect",
    [
        ("How can I increase my ATS score quickly?", True),
        ("machine learning", False),
    ],
)
def test_carl_grounding_suggested_vs_irrelevant(msg: str, expect: bool):
    snap = _carl_snapshot()
    snap["suggestedPrompts"] = [
        "How can I increase my ATS score quickly?",
        "Second prompt for testing",
        "Third prompt for testing",
    ]
    assert is_carl_message_grounded(msg, snap) is expect


# --- HTTP: public smoke -------------------------------------------------------


def test_http_landing_ok(client):
    assert client.get("/").status_code == 200


def test_http_jobs_ok(client):
    assert client.get("/jobs").status_code == 200


def test_http_jobs_second_page_ok(client):
    assert client.get("/jobs?page=2").status_code == 200


def test_http_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data.get("ok") is True
    inner = data.get("data", {})
    assert inner.get("status") == "ok"
    assert "db_latency_ms" in inner
    assert isinstance(inner.get("db_latency_ms"), (int, float))


def test_http_sitemap_xml(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert b"urlset" in r.data


def test_http_robots_txt(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert b"Sitemap:" in r.data


def test_http_safe_parse_search_params_basic():
    t, c, sf, sc = safe_parse_search_params("engineer remote", "US")
    assert "engineer" in t or t
    assert c


def test_http_slugify_job_title():
    assert "senior" in slugify_job_title("Senior Engineer!!!")


# --- HTTP: prod-facing surfaces ---------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/about", "/pricing", "/legal", "/developers", "/market-research"],
)
def test_http_marketing_pages_ok(client, path):
    assert client.get(path).status_code == 200


def test_http_api_jobs_json_envelope(client):
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert "application/json" in (r.headers.get("Content-Type") or "")
    data = r.get_json()
    assert data is not None
    assert data.get("ok") is True
    assert "data" in data


def test_http_v1_jobs_without_key_401(client):
    r = client.get("/v1/jobs")
    assert r.status_code == 401
    assert r.get_json().get("error") == "invalid_key"


def test_http_api_unknown_path_404_envelope(client):
    r = client.get("/api/this-route-does-not-exist-xyz")
    assert r.status_code == 404
    data = r.get_json()
    assert data.get("ok") is False
    assert data.get("code") == "not_found"


def test_http_security_headers_on_homepage(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy")
    assert r.headers.get("Cross-Origin-Opener-Policy")


def test_http_x_request_id_header(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID")


def test_http_unknown_html_path_404(client):
    r = client.get("/totally-missing-page-12345")
    assert r.status_code == 404
    data = r.get_json()
    assert data is not None
    assert data.get("error") == "not found"


def test_http_remote_redirects_to_jobs(client):
    r = client.get("/remote", follow_redirects=False)
    assert r.status_code == 301
    loc = r.headers.get("Location", "")
    assert "/jobs" in loc
    assert "Remote" in loc or "remote" in loc.lower()


def test_http_static_tailwind_css_served(client):
    tw = Path(__file__).resolve().parents[1] / "app" / "static" / "css" / "tailwind.css"
    if not tw.is_file():
        pytest.skip("tailwind.css is gitignored; add a local build to exercise this path")
    r = client.get("/static/css/tailwind.css")
    assert r.status_code == 200
    assert "text/css" in (r.headers.get("Content-Type") or "").lower()
    assert len(r.data) > 500


def test_http_salary_tool_redirect(client):
    r = client.get("/salary-tool", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers.get("Location")


def test_http_health_deep_includes_db_latency(client):
    r = client.get("/health?deep=1")
    assert r.status_code == 200
    inner = r.get_json().get("data", {})
    assert inner.get("deep") is True
    assert inner.get("db_latency_ms") is not None


# --- HTTP: Carl (stubbed profile write) -------------------------------------


def test_carl_get_redirects_guest(carl_client):
    r = carl_client.get("/carl", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/register" in r.headers.get("Location", "")


def test_carl_get_ok_when_logged_in(carl_client):
    _carl_login(carl_client)
    r = carl_client.get("/carl")
    assert r.status_code == 200
    assert "csrf_token" in r.get_data(as_text=True)


def test_carl_analyze_requires_login(carl_client):
    r = carl_client.post("/carl/analyze", data={})
    assert r.status_code == 401
    body = r.get_json()
    assert body.get("ok") is False
    assert body.get("code") == "login_required"


def test_carl_chat_turn_limit_and_grounding(carl_client):
    _carl_login(carl_client)
    page = carl_client.get("/carl")
    csrf = _csrf_from_carl_page(page.get_data(as_text=True))

    cv_text = (
        "Senior backend engineer python aws docker kubernetes "
        "10 years experience microservices San Francisco"
    )
    ar = carl_client.post(
        "/carl/analyze",
        data={"csrf_token": csrf, "cv_text": cv_text},
        headers={"X-CSRF-Token": csrf},
    )
    assert ar.status_code == 200, ar.get_data(as_text=True)[:500]
    body = ar.get_json()
    data = body["data"]
    analysis = data["analysis"]
    assert data["profile_sync"]["status"] == "saved"
    assert data["profile_sync"].get("saved_at")
    assert "supabase" in "\n".join(data["analysis"].get("terminalLogs") or []).lower()
    prompts = analysis["chatContext"]["suggestedPrompts"]
    assert len(prompts) == 3

    def chat(payload: Dict[str, Any]):
        return carl_client.post(
            "/carl/chat",
            json=payload,
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )

    bad = chat({"message": "What is the capital of Mongolia?"})
    assert bad.status_code == 400
    assert bad.get_json().get("code") == "chat_not_grounded"

    r1 = chat({"prompt_id": 0})
    assert r1.status_code == 200
    d1 = r1.get_json()["data"]
    assert "reply" in d1
    assert d1.get("chat_limit_reached") is not True

    assert chat({"message": prompts[1]}).status_code == 200

    r3 = chat({"message": "Main risk is keyword coverage gaps — thoughts?"})
    assert r3.status_code == 200
    d3 = r3.get_json()["data"]
    assert d3.get("chat_limit_reached") is True
    assert d3.get("cta", {}).get("developers")

    r4 = chat({"prompt_id": 2})
    assert r4.status_code == 200
    d4 = r4.get_json()["data"]
    assert d4.get("chat_limit_reached") is True
    assert "reply" in d4


def test_carl_analyze_merges_cv_meta_payload(carl_client, monkeypatch):
    captured: list = []

    def _capture(user_id: str, cv_text: str, meta: Dict[str, Any], email=None):
        captured.append(meta)
        return "ok"

    monkeypatch.setattr(app_factory, "upsert_profile_cv_extract", _capture)
    _carl_login(carl_client)
    page = carl_client.get("/carl")
    csrf = _csrf_from_carl_page(page.get_data(as_text=True))
    ar = carl_client.post(
        "/carl/analyze",
        data={"csrf_token": csrf, "cv_text": "python engineer aws 5 years"},
        headers={"X-CSRF-Token": csrf},
    )
    assert ar.status_code == 200
    assert len(captured) == 1
    meta = captured[0]
    assert "carl" in meta
    assert meta["carl"].get("headline")
    assert "saved_at" in meta["carl"]
    assert meta.get("inputType") == "text"


# --- HTTP: Carl + Postgres (opt-in, no stub) ----------------------------------

_RUN_CARL_DB = os.getenv("RUN_CARL_DB_INTEGRATION", "").strip().lower() in ("1", "true", "yes")
_CARL_UID = (os.getenv("CARL_TEST_USER_ID") or "").strip()


@pytest.mark.skipif(not _RUN_CARL_DB, reason="Set RUN_CARL_DB_INTEGRATION=1 for live profiles write + readback.")
@pytest.mark.skipif(not _CARL_UID, reason="Set CARL_TEST_USER_ID (auth.users UUID).")
def test_carl_analyze_live_profiles_cv_meta_carl(app):
    import psycopg

    from app.models.db import SUPABASE_URL

    if not SUPABASE_URL:
        pytest.skip("DATABASE_URL / SUPABASE_URL not configured.")

    client = app.test_client()
    email = (os.getenv("CARL_TEST_EMAIL") or "carl-db-integration@example.invalid").strip()
    with client.session_transaction() as sess:
        sess["user"] = {"id": _CARL_UID, "email": email}

    page = client.get("/carl")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m
    csrf = m.group(1)

    cv_text = (
        "Senior python engineer aws docker kubernetes "
        "10 years experience integration test cv meta carl block"
    )
    resp = client.post(
        "/carl/analyze",
        data={"csrf_token": csrf, "cv_text": cv_text},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)[:800]
    body = resp.get_json()
    assert body.get("ok") is True, body
    data = body.get("data") or {}
    assert data.get("profile_sync", {}).get("status") == "saved", data.get("profile_sync")
    assert "carl" in "\n".join((data.get("analysis") or {}).get("terminalLogs") or []).lower()

    with psycopg.connect(SUPABASE_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cv_meta::text, length(cv_extracted_text) FROM profiles WHERE id = %s::uuid",
                (_CARL_UID,),
            )
            row = cur.fetchone()

    assert row is not None
    raw_meta, text_len = row[0], row[1]
    assert raw_meta is not None
    assert text_len and int(text_len) > 50

    if isinstance(raw_meta, dict):
        meta = raw_meta
    else:
        meta = json.loads(str(raw_meta))
    assert isinstance(meta, dict)
    assert "carl" in meta
    assert meta["carl"].get("headline")
    assert meta["carl"].get("saved_at")
