"""Production-oriented route and header checks (read-only, no secrets)."""

import pytest


@pytest.mark.parametrize(
    "path",
    [
        "/about",
        "/pricing",
        "/legal",
        "/developers",
        "/market-research",
    ],
)
def test_readonly_marketing_pages_ok(client, path):
    r = client.get(path)
    assert r.status_code == 200


def test_api_jobs_json_envelope(client):
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert "application/json" in (r.headers.get("Content-Type") or "")
    data = r.get_json()
    assert data is not None
    assert data.get("ok") is True
    assert "data" in data


def test_v1_jobs_without_key_401(client):
    r = client.get("/v1/jobs")
    assert r.status_code == 401
    data = r.get_json()
    assert data.get("error") == "invalid_key"


def test_api_unknown_path_404_envelope(client):
    r = client.get("/api/this-route-does-not-exist-xyz")
    assert r.status_code == 404
    data = r.get_json()
    assert data.get("ok") is False
    assert data.get("code") == "not_found"


def test_security_headers_on_homepage(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy")
    assert r.headers.get("Cross-Origin-Opener-Policy")


def test_x_request_id_header(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID")


def test_unknown_html_path_404(client):
    r = client.get("/totally-missing-page-12345")
    assert r.status_code == 404
    data = r.get_json()
    assert data is not None
    assert data.get("error") == "not found"


def test_remote_redirects_to_jobs(client):
    r = client.get("/remote", follow_redirects=False)
    assert r.status_code == 301
    loc = r.headers.get("Location", "")
    assert "/jobs" in loc
    assert "Remote" in loc or "remote" in loc.lower()


def test_static_tailwind_css_served(client):
    r = client.get("/static/css/tailwind.css")
    assert r.status_code == 200
    assert "text/css" in (r.headers.get("Content-Type") or "").lower()
    assert len(r.data) > 500


def test_salary_tool_redirect(client):
    r = client.get("/salary-tool", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers.get("Location")


def test_health_deep_includes_db_latency(client):
    r = client.get("/health?deep=1")
    assert r.status_code == 200
    inner = r.get_json().get("data", {})
    assert inner.get("deep") is True
    assert inner.get("db_latency_ms") is not None
