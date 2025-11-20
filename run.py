#!/usr/bin/env python3
"""Catalitium application entry point.

Exposes the WSGI ``app`` for production and keeps ``python run.py`` for local dev.
"""

import os

try:  # Optional dependency for local development
    from dotenv import load_dotenv  # type: ignore
except ImportError:  # pragma: no cover - dotenv is optional
    load_dotenv = None

if load_dotenv:
    load_dotenv()


def _current_env() -> str:
    return (os.getenv("ENV") or os.getenv("FLASK_ENV") or "production").lower()


ENVIRONMENT = _current_env()

# Provide a predictable SECRET_KEY in local runs so sessions work without extra setup
if ENVIRONMENT != "production" and not os.getenv("SECRET_KEY"):
    os.environ["SECRET_KEY"] = "dev-" + os.urandom(16).hex()

from app.app import create_app  # noqa: E402 (import after env setup)

app = create_app()


def _run_local() -> None:
    host = os.getenv("FLASK_HOST") or ("0.0.0.0" if ENVIRONMENT == "production" else "127.0.0.1")
    port = int(os.getenv("PORT") or os.getenv("FLASK_PORT") or 5000)
    debug_env = os.getenv("FLASK_DEBUG")
    if debug_env is None:
        debug = ENVIRONMENT != "production"
    else:
        debug = debug_env.lower() in {"1", "true", "yes", "on"}
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    _run_local()
