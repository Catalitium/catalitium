"""Public API and v1 routes: API key management + authenticated data endpoints."""

import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict

from flask import Blueprint, g, jsonify, render_template, request, session

from ..utils import (
    BLACKLIST_LINKS,
    api_error_response,
    api_success_response,
    coerce_datetime,
    job_is_new,
    require_api_key,
    resolve_pagination,
)
from ..models.catalog import Job, clean_job_description_text, get_job_summary, save_job_summary
from ..models.db import logger
from ..models.api_keys import (
    confirm_api_key_by_token,
    create_api_key,
    get_api_key_by_email,
    revoke_api_key,
)
from ..models.money import get_salary_for_location
from ..utils import send_api_key_activation

bp = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# API key lifecycle
# ---------------------------------------------------------------------------

@bp.post("/api/keys/register")
def api_keys_register():
    """Register a new API key. Requires an active Catalitium account (session login)."""
    user = session.get("user")
    if not user:
        return api_error_response(
            "login_required",
            "Sign in to your Catalitium account first.",
            401,
        )

    email = (user.get("email") or "").strip()
    user_id = str(user.get("id") or "")
    if not email:
        return api_error_response("account_email_missing", "Account email is missing.", 400)

    existing = get_api_key_by_email(email)
    if existing:
        if existing.get("is_active"):
            return jsonify({"message": "A key for this account already exists. Check your inbox for the original activation email."}), 200
        return jsonify({"message": "A confirmation is already pending. Check your inbox or try again in 24 hours."}), 200

    raw_key = "cat_" + secrets.token_hex(22)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]
    confirm_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    ip = request.remote_addr

    ok = create_api_key(
        email=email,
        key_hash=key_hash,
        key_prefix=key_prefix,
        confirm_token=confirm_token,
        confirm_token_expires_at=expires_at,
        created_from_ip=ip,
        user_id=user_id,
    )
    if not ok:
        return api_error_response("registration_failed", "Could not register API key.", 500)

    base_url = request.host_url.rstrip("/")
    confirm_url = f"{base_url}/api/keys/confirm?token={confirm_token}"
    send_api_key_activation(email, raw_key, confirm_url)
    logger.info("API key created prefix=%s ip=%s email=%s user_id=%s", key_prefix, ip, email, user_id)
    return jsonify({"message": "Check your email to activate your key."}), 200


@bp.get("/api/keys/confirm")
def api_keys_confirm():
    """Activate an API key using the token from the confirmation email."""
    token = (request.args.get("token") or "").strip()
    if not token:
        return api_error_response("token_required", "Confirmation token is required.", 400)
    ok = confirm_api_key_by_token(token, datetime.now(timezone.utc))
    if not ok:
        return api_error_response("invalid_or_expired_token", "Invalid or expired confirmation token.", 400)
    return jsonify({"message": "Key activated. Your API key was included in the confirmation email you received."}), 200


@bp.get("/api/keys/usage")
@require_api_key
def api_keys_usage():
    """Return daily usage stats for the authenticated API key."""
    rec = g.get("api_key_record", {})
    now = datetime.now(timezone.utc)
    reset_dt = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return jsonify({
        "tier": rec.get("tier"),
        "daily_limit": rec.get("daily_limit", 50),
        "requests_today": rec.get("requests_today", 0),
        "monthly_limit": rec.get("monthly_limit", 500),
        "requests_this_month": rec.get("requests_this_month", 0),
        "reset_date": reset_dt.isoformat(),
    }), 200


@bp.delete("/api/keys/me")
def api_keys_revoke():
    """Revoke the API key supplied in X-API-Key (does not consume quota)."""
    raw_key = (
        request.headers.get("X-API-Key")
        or request.args.get("api_key")
        or ""
    ).strip()
    if not raw_key:
        return api_error_response("invalid_key", "A valid API key is required.", 401)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    ok = revoke_api_key(key_hash)
    if not ok:
        return api_error_response("invalid_key", "Invalid or revoked API key.", 401)
    return jsonify({"message": "Key revoked."}), 200


# ---------------------------------------------------------------------------
# v1/ authenticated data API
# ---------------------------------------------------------------------------

@bp.get("/v1/jobs")
@require_api_key
def v1_jobs():
    """Authenticated job search; same parameters as /api/jobs."""
    from ..utils import normalize_country, normalize_title
    from ..models.money import parse_salary_query

    raw_title = (request.args.get("title") or "").strip()
    raw_country = (request.args.get("country") or "").strip()
    page, per_page = resolve_pagination()

    try:
        cleaned_title, sal_floor, sal_ceiling = parse_salary_query(raw_title or "")
        title_q = normalize_title(cleaned_title)
        country_q = normalize_country(raw_country or "")
    except Exception:
        title_q, country_q = "", ""

    q_title = title_q or None
    q_country = country_q or None
    offset = (max(1, page) - 1) * per_page

    try:
        total = Job.count(q_title, q_country)
    except Exception:
        total = None
    try:
        rows = Job.search(q_title, q_country, limit=per_page, offset=offset)
    except Exception:
        rows = []
    if total is None:
        total = len(rows)

    items = []
    for row in rows:
        link = row.get("link")
        if link in BLACKLIST_LINKS:
            link = None
        date_raw = row.get("date")
        date_str = ""
        if date_raw:
            dt = coerce_datetime(date_raw)
            if dt:
                date_str = dt.date().isoformat()
        items.append({
            "id": row.get("id"),
            "title": (row.get("job_title") or "").strip(),
            "company": (row.get("company_name") or "").strip(),
            "location": row.get("location") or "",
            "description": clean_job_description_text(row.get("job_description") or ""),
            "apply_url": link or "",
            "salary_range": row.get("job_salary_range") or "",
            "date_posted": date_str,
            "is_new": job_is_new(date_raw, date_raw),
        })

    pages = max(1, (total + per_page - 1) // per_page) if total else 1
    return jsonify({
        "items": items,
        "meta": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": pages,
            "title": title_q or "",
            "country": country_q or "",
        },
    }), 200


@bp.get("/v1/jobs/<int:job_id>")
@require_api_key
def v1_job_detail(job_id: int):
    """Return a single job as JSON."""
    row = Job.get_by_id(str(job_id))
    if not row:
        return api_error_response("not_found", "Job not found", 404)
    link = row.get("link")
    if link in BLACKLIST_LINKS:
        link = None
    date_raw = row.get("date")
    date_str = ""
    if date_raw:
        dt = coerce_datetime(date_raw)
        if dt:
            date_str = dt.date().isoformat()
    return jsonify({
        "id": job_id,
        "title": re.sub(r"\s+", " ", (row.get("job_title") or "").strip()),
        "company": (row.get("company_name") or "").strip(),
        "location": row.get("location") or "",
        "description": clean_job_description_text(row.get("job_description") or ""),
        "apply_url": link or "",
        "salary_range": row.get("job_salary_range") or "",
        "date_posted": date_str,
        "is_new": job_is_new(date_raw, date_raw),
    }), 200


@bp.get("/v1/salary")
@require_api_key
def v1_salary():
    """Return salary lookup for a title+country combination."""
    raw_title = (request.args.get("title") or "").strip()
    raw_country = (request.args.get("country") or "").strip()
    location = raw_country or raw_title or ""
    try:
        rec = get_salary_for_location(location)
    except Exception:
        rec = None
    if not rec:
        return api_error_response("no_data", "No salary data for this location.", 404)
    median, currency = rec[0], rec[1]
    return jsonify({
        "location": location,
        "median_salary": median,
        "currency": currency,
    }), 200


# ---------------------------------------------------------------------------
# AI Job Summary API (DB-cached)
# ---------------------------------------------------------------------------

@bp.get("/api/summary/<int:job_id>")
def api_summary(job_id: int):
    """Return AI-generated bullets + skill tags for a job (cached in DB)."""
    empty_summary = {"bullets": [], "skills": []}
    cached = get_job_summary(job_id)
    if cached:
        return api_success_response(cached)

    row = Job.get_by_id(str(job_id))
    if not row:
        return api_error_response("not_found", "Job not found", 404)

    description = (row.get("job_description") or "").strip()
    if len(description) < 50:
        return api_success_response(empty_summary, code="summary_unavailable", message="description_too_short")

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return api_success_response(empty_summary, code="summary_unavailable", message="provider_not_configured")

    from ..app import _call_anthropic
    bullets, skills = _call_anthropic(description, api_key)
    if bullets is None:
        return api_success_response(empty_summary, code="summary_unavailable", message="provider_request_failed")

    try:
        save_job_summary(job_id, bullets, skills)
    except Exception:
        pass

    return api_success_response({"bullets": bullets, "skills": skills})
