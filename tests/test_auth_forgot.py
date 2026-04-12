"""Password reset request and token session bridge (mocked Supabase)."""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

def _csrf_from_register_page(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "csrf_token missing from register page"
    return m.group(1)


def test_register_tab_login_query(client):
    r = client.get("/register?tab=login")
    assert r.status_code == 200
    assert b"id=\"tab-login\"" in r.data
    assert b"Forgot password?" in r.data


def test_auth_forgot_calls_supabase_and_redirects(client):
    page = client.get("/register?tab=login")
    assert page.status_code == 200
    token = _csrf_from_register_page(page.get_data(as_text=True))
    mock_sb = MagicMock()
    mock_sb.auth.reset_password_for_email = MagicMock()
    with patch("app.factory._get_supabase", return_value=mock_sb):
        r = client.post(
            "/auth/forgot",
            data={"email": "user@example.com", "csrf_token": token},
            follow_redirects=False,
        )
    assert r.status_code in (302, 303)
    loc = r.headers.get("Location", "")
    assert "/register" in loc
    mock_sb.auth.reset_password_for_email.assert_called_once()
    call_args = mock_sb.auth.reset_password_for_email.call_args
    assert call_args is not None
    pos = call_args[0]
    assert pos[0] == "user@example.com"
    opts = pos[1] if len(pos) > 1 else call_args[1].get("options") or call_args[1]
    assert isinstance(opts, dict) and opts.get("redirect_to")


def test_auth_forgot_without_supabase_still_redirects(client):
    page = client.get("/register?tab=login")
    token = _csrf_from_register_page(page.get_data(as_text=True))
    with patch("app.factory._get_supabase", return_value=None):
        r = client.post(
            "/auth/forgot",
            data={"email": "anyone@example.com", "csrf_token": token},
            follow_redirects=False,
        )
    assert r.status_code in (302, 303)


def test_auth_session_requires_csrf(client):
    r = client.post("/auth/session", json={"access_token": "x"}, headers={"Content-Type": "application/json"})
    assert r.status_code == 403


def test_auth_session_sets_flask_session(client):
    confirm = client.get("/auth/confirm")
    assert confirm.status_code == 200
    token = _csrf_from_register_page(confirm.get_data(as_text=True))

    mock_user = MagicMock()
    mock_user.id = "11111111-1111-1111-1111-111111111111"
    mock_user.email = "signed-in@example.com"
    mock_user.user_metadata = {"account_type": "candidate", "hire_access": False}
    mock_ures = MagicMock()
    mock_ures.user = mock_user
    mock_sb = MagicMock()
    mock_sb.auth.get_user = MagicMock(return_value=mock_ures)

    with patch("app.factory._get_supabase", return_value=mock_sb):
        r = client.post(
            "/auth/session",
            json={"access_token": "fake.jwt.token", "refresh_token": ""},
            headers={"Content-Type": "application/json", "X-CSRF-Token": token},
        )
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("ok") is True
    assert body.get("redirect")
    mock_sb.auth.get_user.assert_called_once_with("fake.jwt.token")


def test_compare_route_removed(client):
    r = client.get("/compare")
    assert r.status_code == 404
