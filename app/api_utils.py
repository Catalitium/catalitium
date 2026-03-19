"""Shared API helpers for response envelopes, validation, and caching."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Mapping, Optional


def generate_request_id() -> str:
    """Return a short request correlation id."""
    return uuid.uuid4().hex[:12]


def api_ok(
    *,
    data: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    message: str = "ok",
    code: str = "ok",
) -> Dict[str, Any]:
    """Return a normalized success envelope."""
    return {
        "ok": True,
        "code": code,
        "message": message,
        "request_id": request_id or "",
        "data": data or {},
    }


def api_fail(
    *,
    code: str,
    message: str,
    request_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a normalized error envelope."""
    return {
        "ok": False,
        "code": code,
        "message": message,
        "request_id": request_id or "",
        "details": details or {},
    }


def parse_int_arg(
    args: Mapping[str, Any],
    key: str,
    *,
    default: int,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    """Parse and clamp an integer query parameter."""
    raw = args.get(key, default)
    try:
        value = int(raw)  # type: ignore[arg-type]
    except Exception:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def parse_str_arg(args: Mapping[str, Any], key: str, *, default: str = "", max_len: int = 200) -> str:
    """Parse and trim a string query parameter."""
    value = str(args.get(key, default) or "").strip()
    return value[:max_len]


class TTLCache:
    """Simple in-memory TTL cache suitable for low-volume API responses."""

    def __init__(self, ttl_seconds: int = 60, max_size: int = 500) -> None:
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_size = max(10, int(max_size))
        self._store: Dict[str, tuple[float, Any]] = {}

    def _prune(self) -> None:
        now = time.time()
        expired = [k for k, (ts, _) in self._store.items() if now - ts > self.ttl_seconds]
        for key in expired:
            self._store.pop(key, None)
        if len(self._store) <= self.max_size:
            return
        oldest = sorted(self._store.items(), key=lambda kv: kv[1][0])[: len(self._store) - self.max_size]
        for key, _ in oldest:
            self._store.pop(key, None)

    def get(self, key: str) -> Any:
        hit = self._store.get(key)
        if not hit:
            return None
        ts, value = hit
        if time.time() - ts > self.ttl_seconds:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._prune()
        self._store[key] = (time.time(), value)
