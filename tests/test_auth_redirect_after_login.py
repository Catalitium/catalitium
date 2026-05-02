"""Post-login redirect must honor Carl (Individuals) and Carl B2B, not only market research."""

from __future__ import annotations

import pytest

from app.controllers.auth import _redirect_after_login_allowed


@pytest.mark.parametrize(
    "path,ok",
    [
        ("/market-research/foo", True),
        ("/carl", True),
        ("/carl?csrf_token=x&foo=1", True),
        ("/carl/b2b", True),
        ("/carl/b2b?x=1", True),
        ("/studio", False),
        ("//evil.com", False),
        ("https://evil.com", False),
        ("/carl\x0aLocation:evil", False),
    ],
)
def test_redirect_after_login_allowed(path: str, ok: bool) -> None:
    assert _redirect_after_login_allowed(path) is ok


def test_carl_guest_get_does_not_store_redirect_path(app) -> None:
    client = app.test_client()
    r = client.get("/carl?csrf_token=test&cv_file=x.pdf", follow_redirects=False)
    assert r.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("redirect_after_login") is None
