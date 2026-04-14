"""Pytest configuration: env defaults and shared Flask fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

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

os.environ.setdefault("SECRET_KEY", "pytest-secret-key-not-for-production")
# ``app.config.SUPABASE_URL`` must be non-empty or ``create_app()`` exits. GitHub Actions
# sometimes sets ``DATABASE_URL=""`` (key present, value empty); ``setdefault`` would not
# override that, so we assign explicitly when no usable URL is configured.
_PYTEST_DB_PLACEHOLDER = "postgresql://127.0.0.1:65534/pytest_nonexistent"
_effective_db = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or "").strip()
if not _effective_db:
    os.environ["DATABASE_URL"] = _PYTEST_DB_PLACEHOLDER


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
