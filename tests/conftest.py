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
except ImportError:
    pass

os.environ.setdefault("SECRET_KEY", "pytest-secret-key-not-for-production")
# Do not inject a fake DATABASE_URL if ``.env`` (or the shell) already set ``SUPABASE_URL`` only.
if not (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or "").strip():
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql://127.0.0.1:65534/pytest_nonexistent",
    )


@pytest.fixture()
def app():
    """Single app instance per test (TESTING mode)."""
    from app.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    """HTTP client for route tests (smoke, prod readiness, most integration tests)."""
    return app.test_client()
