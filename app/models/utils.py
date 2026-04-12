"""Shared model-layer utilities.

Deduplicates helpers that were copy-pasted across users.py, salary.py,
and ad-hoc salary-context wrappers in app.py routes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from .money import get_salary_for_location
from .db import logger


def now_iso() -> str:
    """UTC timestamp in ISO-8601 seconds precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_salary_context(location: str) -> Dict[str, Any]:
    """Wrap ``get_salary_for_location`` with standardized None handling.

    Returns a dict with keys: ``median``, ``currency``, ``raw`` (the
    original tuple or None).  Callers never need to unpack/guard against
    None themselves.
    """
    result: Optional[Tuple[float, Optional[str]]] = None
    try:
        if location:
            result = get_salary_for_location(location)
    except Exception as exc:
        logger.debug("safe_salary_context(%r) lookup failed: %s", location, exc)

    if result and result[0] is not None:
        return {
            "median": float(result[0]),
            "currency": result[1] or None,
            "raw": result,
        }
    return {
        "median": None,
        "currency": None,
        "raw": None,
    }
