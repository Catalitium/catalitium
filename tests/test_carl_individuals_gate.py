"""Carl /carl: Individuals persona gate must work for signed-in users (HTML + inline wire).

Regression: inline ``data-carl-gate-wire`` runs during parse so ``For Individuals`` reveals the workspace.
Upload form must use POST to ``/carl/analyze`` so a missed JS intercept does not default to GET (query-string URL).
carl.js loads without ``defer`` so handlers bind sooner on production (consent/Cookiebot delays).
"""

from __future__ import annotations

import re

import pytest


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
    """Non-negotiable: inline wire must exist and reference the three DOM ids (real browser behavior)."""
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
    assert idx_btn < idx_workspace < idx_wire, "button and workspace must appear before inline wire script"


def test_carl_guest_redirects_no_gate(app):
    """Unauthenticated users never see the Individuals gate (redirect to register)."""
    guest = app.test_client()
    r = guest.get("/carl", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "btn-select-individual" not in (r.get_data(as_text=True) or "")


def test_carl_js_linked_and_upload_form_no_fullpage_analyze(carl_logged_in_client):
    r = carl_logged_in_client.get("/carl")
    html = r.get_data(as_text=True)
    assert re.search(r'<script[^>]+src=["\'][^"\']*js/carl\.js', html) is not None
    assert 'id="carl-upload-form"' in html
    assert 'method="post"' in html
    assert 'id="carl-upload-btn"' in html and 'type="button"' in html
    assert "onsubmit=" in html
