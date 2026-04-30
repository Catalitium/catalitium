"""Pytest configuration: env defaults and shared Flask fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_PYTEST_DB_PLACEHOLDER = "postgresql://127.0.0.1:65534/pytest_nonexistent"


def _ensure_test_db_url() -> None:
    """``app.config.SUPABASE_URL`` must be non-empty or ``create_app()`` exits.

    Run before/after dotenv: CI may export ``DATABASE_URL=""``, and ``app.config`` is
    populated at import time — this must run before any ``import app`` loads config.
    """
    effective = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or "").strip()
    if not effective:
        os.environ["DATABASE_URL"] = _PYTEST_DB_PLACEHOLDER


_ensure_test_db_url()

# Load repo ``.env`` first so local/prod-like credentials win over pytest fallbacks
# (``.env`` is gitignored; CI should inject env vars instead).
try:
    from dotenv import load_dotenv

    _repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(_repo_root / ".env", override=False)
    # Worktree dev: reuse main repo .env when this tree has no local file
    if not (_repo_root / ".env").is_file():
        _main_env = _repo_root.parent.parent / ".env"
        if _main_env.is_file():
            load_dotenv(dotenv_path=_main_env, override=False)
except ImportError:
    pass

_ensure_test_db_url()

os.environ.setdefault("SECRET_KEY", "pytest-secret-key-not-for-production")

# Live Carl + Postgres (opt-in): ``RUN_CARL_DB_INTEGRATION`` and ``CARL_TEST_USER_ID`` in ``tests/test_catalitium.py``.


@pytest.fixture()
def app():
    """Single app instance per test (TESTING mode)."""
    from app.factory import create_app

    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    """HTTP client for route tests (smoke, prod readiness, most integration tests)."""
    return app.test_client()


@pytest.fixture
def mock_db_health_ok(monkeypatch):
    """Stub ``get_db`` so ``GET /health`` returns 200 when CI has no Postgres (connection refused).

    ``/health`` lives in ``app.controllers.jobs`` and uses a module-level ``from ..models.db import
    get_db``, so patching only ``app.models.db.get_db`` does not replace that bound name. Patch
    both the definition and the consumer used by the route.
    """
    from app.controllers import jobs as jobs_mod
    from app.models import db as db_mod

    class _Cur:
        def execute(self, *a, **k):
            return None

        def fetchone(self):
            return (1,)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    class _Conn:
        def cursor(self):
            return _Cur()

    fake = lambda: _Conn()

    monkeypatch.setattr(db_mod, "get_db", fake)
    monkeypatch.setattr(jobs_mod, "get_db", fake)
