"""Lightweight anti-spam helpers for public write endpoints (no Cloudflare required)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping, Optional, Tuple

# Must match `snippets/_honeypot_field.html` name= attribute.
HONEYPOT_FIELD = "hp_company_url"

_MAX_CONTACT_NAME = 120
_MAX_CONTACT_MESSAGE = 1200

_URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)

_DISPOSABLE_DOMAINS = frozenset(
    {
        "mailinator.com",
        "guerrillamail.com",
        "guerrillamailblock.com",
        "sharklasers.com",
        "yopmail.com",
        "yopmail.net",
        "trashmail.com",
        "tempmail.com",
        "dispostable.com",
        "maildrop.cc",
        "getairmail.com",
        "10minutemail.com",
        "fakeinbox.com",
        "burnermail.io",
        "trashmail.de",
        "mailnesia.com",
        "mailcatch.com",
        "temp-mail.org",
        "emailondeck.com",
        "throwaway.email",
        "grr.la",
        "moza.pl",
        "byom.de",
        "spam4.me",
        "mailnull.com",
        "mailscrap.com",
        "tmpmail.net",
        "tmpmail.org",
    }
)


def _payload_get(payload: Mapping[str, Any], key: str) -> str:
    try:
        v = payload.get(key)
    except Exception:
        return ""
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    return str(v).strip()


def honeypot_triggered(payload: Mapping[str, Any]) -> bool:
    """True when the honeypot field is non-empty (typical bot behavior)."""
    return bool(_payload_get(payload, HONEYPOT_FIELD))


def disposable_email_domain(email: str) -> bool:
    """True for common throwaway inboxes (best-effort list)."""
    at = (email or "").rfind("@")
    if at < 0:
        return False
    dom = email[at + 1 :].lower().strip()
    if dom in _DISPOSABLE_DOMAINS:
        return True
    return any(dom.endswith("." + d) for d in _DISPOSABLE_DOMAINS)


def _too_many_links(text: str, max_links: int = 5) -> bool:
    return len(_URL_RE.findall(text or "")) > max_links


def _only_urls(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    remainder = _URL_RE.sub("", t)
    remainder = re.sub(r"\s+", "", remainder)
    return len(remainder) == 0


def _repetition_spam(s: str) -> bool:
    """Detects keyboard-mash style strings (one character dominates)."""
    s2 = "".join(c for c in (s or "").lower() if c.isalnum())
    if len(s2) < 16:
        return False
    top = Counter(s2).most_common(1)[0][1]
    return (top / len(s2)) >= 0.55


def prepare_contact_submission(name: str, message: str) -> Optional[Tuple[str, str]]:
    """Return (name, message) ready for INSERT, or None if it should not be stored."""
    n = (name or "").strip()
    m = (message or "").strip()
    if len(n) > _MAX_CONTACT_NAME:
        n = n[:_MAX_CONTACT_NAME].strip()
    if len(m) > _MAX_CONTACT_MESSAGE:
        m = m[:_MAX_CONTACT_MESSAGE].strip()

    low_msg = m.lower()
    low_name = n.lower()
    if "<script" in low_msg or "<script" in low_name:
        return None
    if _too_many_links(m) or _only_urls(m):
        return None
    if _repetition_spam(m) or _repetition_spam(n):
        return None
    return (n, m)
