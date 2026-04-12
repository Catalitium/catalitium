"""Format-only email validation for public forms."""

import re

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class EmailNotValidError(ValueError):
    """Raised when an email address fails basic format validation."""


def validate_email(email: str, *, check_deliverability: bool = False):  # noqa: ARG001
    """Lightweight format-only email validator. Returns an object with .normalized."""
    class _Result:
        normalized: str

    r = _Result()
    r.normalized = email.strip().lower()
    if not _EMAIL_RE.match(r.normalized):
        raise EmailNotValidError(f"Invalid email: {email!r}")
    return r
