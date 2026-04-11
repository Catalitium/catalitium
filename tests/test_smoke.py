"""Smoke tests for critical routes and shared helpers."""

import pytest

from app.app import safe_parse_search_params
from app.utils.text import slugify_job_title


def test_landing_ok(client):
    r = client.get("/")
    assert r.status_code == 200


def test_jobs_ok(client):
    r = client.get("/jobs")
    assert r.status_code == 200


def test_jobs_second_page_ok(client):
    """Pagination uses ?page= (not /jobs/page/N)."""
    r = client.get("/jobs?page=2")
    assert r.status_code == 200


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data.get("ok") is True
    inner = data.get("data", {})
    assert inner.get("status") == "ok"
    assert "db_latency_ms" in inner
    assert isinstance(inner.get("db_latency_ms"), (int, float))


def test_sitemap_xml(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert b"urlset" in r.data


def test_robots_txt(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert b"Sitemap:" in r.data


def test_safe_parse_search_params_basic():
    t, c, sf, sc = safe_parse_search_params("engineer remote", "US")
    assert "engineer" in t or t
    assert c


def test_slugify_job_title():
    assert "senior" in slugify_job_title("Senior Engineer!!!")
