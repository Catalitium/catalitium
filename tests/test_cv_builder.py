"""CV Builder: Harvard DOCX generation routes."""

from __future__ import annotations

import re

import pytest

import app.controllers.cv_builder as cv_builder_mod


@pytest.fixture()
def cv_builder_client(app, monkeypatch):
    monkeypatch.setattr(
        cv_builder_mod,
        "extract_cv_structure",
        lambda _text: {
            "name": "Test User",
            "contact_line": "City · test@example.invalid",
            "education": [],
            "experience": [],
            "activities": [],
            "skills": {"technical": "", "language": "", "laboratory": "", "interests": ""},
        },
    )
    return app.test_client()


def _csrf_from_page(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m, "csrf_token missing on /cv-builder"
    return m.group(1)


def test_cv_builder_get_ok(cv_builder_client):
    r = cv_builder_client.get("/cv-builder")
    assert r.status_code == 200
    assert b"cv-builder-form" in r.data


def test_cv_builder_post_rejects_missing_csrf(cv_builder_client):
    r = cv_builder_client.post(
        "/cv-builder/generate",
        data={"cv_text": "Some CV text"},
    )
    assert r.status_code == 400
    body = r.get_json(silent=True) or {}
    assert body.get("ok") is False
    assert body.get("code") == "invalid_csrf"


def test_cv_builder_post_docx_with_text(cv_builder_client):
    r0 = cv_builder_client.get("/cv-builder")
    csrf = _csrf_from_page(r0.get_data(as_text=True))
    r = cv_builder_client.post(
        "/cv-builder/generate",
        data={
            "csrf_token": csrf,
            "cv_text": "Jane Doe\n\nEducation\nUniversity\nDegree 2020",
        },
    )
    assert r.status_code == 200
    assert r.mimetype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert len(r.data) > 2000
    assert r.data[:2] == b"PK"  # ZIP / docx
