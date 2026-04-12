"""Authentication, profile, hire, and account management routes."""

from __future__ import annotations

import os
import secrets
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

try:
    from supabase import create_client as _sb_create_client
except ImportError:
    _sb_create_client = None  # type: ignore[assignment]

from ..models.db import logger
from ..models.identity import get_api_key_by_email, get_user_subscriptions
from ..utils import csrf_valid, validate_email

bp = Blueprint("auth", __name__)

_supabase_clients: dict = {}  # keyed "user" and "admin" — kept separate intentionally
                              # (mixing user-auth and admin clients overwrites session state)

_PROFILE_FIELDS = ("full_name", "headline", "location", "bio", "website")
_ACCOUNT_TYPES = {"candidate", "recruiter", "company"}
_HIRE_ACCOUNT_TYPES = {"recruiter", "company"}
_HIRE_FIELDS = ("company_name", "company_website", "company_size", "hiring_regions")


def _derive_supabase_project_url() -> str:
    project_url = os.getenv("SUPABASE_PROJECT_URL", "").strip()
    if project_url:
        return project_url
    db_url = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or "").strip()
    if not db_url:
        return ""
    parsed = urlparse(db_url)
    username = (parsed.username or "").strip()
    if username.startswith("postgres."):
        ref = username.split(".", 1)[1]
        if ref:
            return f"https://{ref}.supabase.co"
    return ""


def _get_supabase_client(admin: bool = False) -> Optional[Any]:
    """Return a cached Supabase client.

    admin=False → user-auth client (sign_in, sign_up, sign_out).
    admin=True  → admin client (auth.admin.* only).
    Two separate instances are intentional: mixing them overwrites session state."""
    key_name = "admin" if admin else "user"
    if key_name not in _supabase_clients and _sb_create_client:
        project_url = _derive_supabase_project_url()
        secret_key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if not project_url or not secret_key:
            logger.warning("Supabase client unavailable (admin=%s): missing SUPABASE_PROJECT_URL or SUPABASE_SECRET_KEY", admin)
            return None
        try:
            _supabase_clients[key_name] = _sb_create_client(project_url, secret_key)
        except Exception as exc:
            logger.warning("Supabase client init failed (admin=%s): %s", admin, exc)
            return None
    return _supabase_clients.get(key_name)


# Convenience aliases so callsites stay readable
def _get_supabase() -> Optional[Any]:
    return _get_supabase_client(admin=False)


def _get_supabase_admin() -> Optional[Any]:
    return _get_supabase_client(admin=True)


def _clean_profile_data(raw: Dict[str, Any]) -> Dict[str, str]:
    cleaned: Dict[str, str] = {}
    for field in _PROFILE_FIELDS:
        val = str(raw.get(field) or "").strip()
        if field == "website" and val and not val.startswith(("http://", "https://")):
            val = f"https://{val}"
        if field == "bio":
            val = val[:500]
        cleaned[field] = val
    return cleaned


def _get_user_profile_metadata(user_id: str) -> tuple[Dict[str, str], Optional[str]]:
    sb = _get_supabase_admin()
    if not sb:
        return _clean_profile_data({}), "Auth service unavailable."
    try:
        res = sb.auth.admin.get_user_by_id(user_id)
        sb_user = getattr(res, "user", None)
        metadata = getattr(sb_user, "user_metadata", None) or {}
        return _clean_profile_data(metadata), None
    except Exception as exc:
        logger.warning("profile read error (user_id=%s): %s", user_id, exc)
        return _clean_profile_data({}), "Could not load your profile right now."


def _save_user_profile_metadata(user_id: str, profile: Dict[str, Any]) -> Optional[str]:
    sb = _get_supabase_admin()
    if not sb:
        return "Auth service unavailable."
    try:
        # Always merge against the full auth metadata payload to avoid
        # dropping unrelated keys like account_type/hire_access.
        current, err = _get_auth_user_metadata(user_id)
        if err and err != "Auth service unavailable.":
            current = {}
        merged = {**current, **_clean_profile_data(profile)}
        sb.auth.admin.update_user_by_id(user_id, {"user_metadata": merged})
        return None
    except Exception as exc:
        logger.warning("profile update error (user_id=%s): %s", user_id, exc)
        return "Could not save your profile. Please try again."


def _normalize_account_type(value: str) -> str:
    account_type = (value or "").strip().lower()
    return account_type if account_type in _ACCOUNT_TYPES else "candidate"


def _is_hire_eligible(account_type: str, hire_access: bool) -> bool:
    return account_type in _HIRE_ACCOUNT_TYPES and bool(hire_access)


def _clean_hire_data(raw: Dict[str, Any]) -> Dict[str, str]:
    cleaned = {
        "company_name": str(raw.get("company_name") or "").strip()[:140],
        "company_website": str(raw.get("company_website") or "").strip()[:250],
        "company_size": str(raw.get("company_size") or "").strip()[:80],
        "hiring_regions": str(raw.get("hiring_regions") or "").strip()[:200],
    }
    if cleaned["company_website"] and not cleaned["company_website"].startswith(("http://", "https://")):
        cleaned["company_website"] = f"https://{cleaned['company_website']}"
    return cleaned


def _get_auth_user_metadata(user_id: str) -> tuple[Dict[str, Any], Optional[str]]:
    sb = _get_supabase_admin()
    if not sb:
        return {}, "Auth service unavailable."
    try:
        res = sb.auth.admin.get_user_by_id(user_id)
        sb_user = getattr(res, "user", None)
        metadata = getattr(sb_user, "user_metadata", None) or {}
        return metadata, None
    except Exception as exc:
        logger.warning("auth metadata read error (user_id=%s): %s", user_id, exc)
        return {}, "Could not load account data right now."


def _update_auth_user_metadata(user_id: str, updates: Dict[str, Any]) -> Optional[str]:
    sb = _get_supabase_admin()
    if not sb:
        return "Auth service unavailable."
    try:
        current, err = _get_auth_user_metadata(user_id)
        if err and err != "Auth service unavailable.":
            current = {}
        merged = {**current, **updates}
        sb.auth.admin.update_user_by_id(user_id, {"user_metadata": merged})
        return None
    except Exception as exc:
        logger.warning("auth metadata update error (user_id=%s): %s", user_id, exc)
        return "Could not save account data right now."


def _get_hire_metadata(user_id: str) -> tuple[Dict[str, str], Optional[str]]:
    metadata, err = _get_auth_user_metadata(user_id)
    hire_data = _clean_hire_data(metadata)
    hire_data["account_type"] = _normalize_account_type(str(metadata.get("account_type") or "candidate"))
    hire_data["hire_access"] = bool(metadata.get("hire_access"))
    return hire_data, err


def _delete_auth_user(user_id: str) -> Optional[str]:
    sb = _get_supabase()
    if not sb:
        return "Auth service unavailable."
    try:
        sb.auth.admin.delete_user(user_id)
        return None
    except TypeError:
        try:
            sb.auth.admin.delete_user(user_id, should_soft_delete=False)
            return None
        except Exception as exc:
            logger.warning("auth user delete error (user_id=%s): %s", user_id, exc)
            return "Could not delete your account right now."
    except Exception as exc:
        logger.warning("auth user delete error (user_id=%s): %s", user_id, exc)
        return "Could not delete your account right now."


@bp.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user"):
        return redirect(url_for("auth.studio"))
    if request.method == "GET":
        from_source = request.args.get("from", "")
        tab = request.args.get("tab", "signup")
        if tab not in {"signup", "login"}:
            tab = "signup"
        return render_template("register.html", tab=tab, account_type="candidate", from_source=from_source)

    action = request.form.get("action", "signup")
    if action not in {"signup", "login"}:
        action = "login"
    email = (request.form.get("email") or "").strip()
    password = (request.form.get("password") or "").strip()
    account_type = _normalize_account_type(request.form.get("account_type", "candidate"))
    if not csrf_valid():
        flash("Session expired. Please try again.", "error")
        return render_template("register.html", tab=action, account_type=account_type), 400
    try:
        email = validate_email(email, check_deliverability=False).normalized
    except Exception:
        flash("Please enter a valid email.", "error")
        return render_template("register.html", tab=action, account_type=account_type), 400

    sb = _get_supabase()
    if not sb:
        flash(
            "Sign-in is temporarily unavailable. Refresh the page in a moment or try again shortly.",
            "error",
        )
        return render_template("register.html", tab=action, account_type=account_type), 503
    try:
        if action == "signup":
            res = sb.auth.sign_up({"email": email, "password": password})
        else:
            res = sb.auth.sign_in_with_password({"email": email, "password": password})
        user = res.user
        if not user:
            flash("Invalid credentials. Please try again.", "error")
            return render_template("register.html", tab=action, account_type=account_type), 401
        user_id = str(user.id)
        user_metadata = getattr(user, "user_metadata", None) or {}
        existing_type = _normalize_account_type(str(user_metadata.get("account_type") or "candidate"))
        target_type = account_type if action == "signup" else existing_type
        existing_hire_access = bool(user_metadata.get("hire_access"))
        if target_type != existing_type:
            metadata_err = _update_auth_user_metadata(user_id, {"account_type": target_type, "hire_access": False})
            if metadata_err and action == "signup":
                flash(metadata_err, "error")
                return render_template("register.html", tab=action, account_type=account_type), 503
        session["user"] = {
            "id": user_id,
            "email": user.email,
            "account_type": target_type,
            "hire_access": existing_hire_access if action == "login" else False,
        }
        next_path = session.pop("redirect_after_login", None)
        if (
            isinstance(next_path, str)
            and next_path.startswith("/market-research/")
            and (not next_path.startswith("//"))
            and "\n" not in next_path
            and "\r" not in next_path
        ):
            return redirect(next_path)
        return redirect(url_for("auth.studio"))
    except Exception as exc:
        logger.warning("auth error (%s): %s", action, exc)
        msg = str(exc).lower()
        if action == "login":
            if "invalid login credentials" in msg:
                flash("Invalid email or password. New here? Use Create account first.", "error")
            elif "email not confirmed" in msg:
                flash("Please confirm your email before signing in.", "error")
            else:
                flash("Sign in failed. Please try again.", "error")
        else:
            if "already registered" in msg or "user already registered" in msg:
                flash("This email already has an account. Please sign in instead.", "error")
            else:
                flash("Create account failed. Please try again.", "error")
        return render_template("register.html", tab=action, account_type=account_type), 400

@bp.post("/auth/forgot")
def auth_forgot_password():
    """Request Supabase password recovery email (no email enumeration in UI copy)."""
    if session.get("user"):
        return redirect(url_for("auth.studio"))
    if not csrf_valid():
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("auth.register", tab="login"))
    email = (request.form.get("email") or "").strip()
    try:
        email = validate_email(email, check_deliverability=False).normalized
    except Exception:
        flash(
            "If an account exists for that address, we sent password reset instructions.",
            "info",
        )
        return redirect(url_for("auth.register", tab="login"))
    sb = _get_supabase()
    if sb:
        try:
            redirect_url = url_for("auth.auth_confirm", _external=True)
            sb.auth.reset_password_for_email(email, {"redirect_to": redirect_url})
        except Exception as exc:
            logger.warning("auth forgot email=%s: %s", email, exc)
    flash(
        "If an account exists for that address, we sent password reset instructions.",
        "info",
    )
    return redirect(url_for("auth.register", tab="login"))

@bp.get("/auth/confirm")
def auth_confirm():
    """Landing page after Supabase redirects with tokens in the URL fragment (implicit flow)."""
    if session.get("user"):
        return redirect(url_for("auth.studio"))
    return render_template("auth_confirm.html")

@bp.post("/auth/session")
def auth_session_from_tokens():
    """Exchange Supabase access_token for a Flask session (used after email recovery link)."""
    if not csrf_valid():
        return jsonify({"ok": False, "error": "csrf"}), 403
    if not request.is_json:
        return jsonify({"ok": False, "error": "bad_request"}), 400
    data = request.get_json(silent=True) or {}
    access_token = (data.get("access_token") or "").strip()
    if not access_token:
        return jsonify({"ok": False, "error": "missing_token"}), 400
    sb = _get_supabase()
    if not sb:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    try:
        ures = sb.auth.get_user(access_token)
        user = getattr(ures, "user", None)
        if not user:
            return jsonify({"ok": False, "error": "invalid_token"}), 401
        user_id = str(user.id)
        user_metadata = getattr(user, "user_metadata", None) or {}
        existing_type = _normalize_account_type(str(user_metadata.get("account_type") or "candidate"))
        existing_hire_access = bool(user_metadata.get("hire_access"))
        session["user"] = {
            "id": user_id,
            "email": user.email,
            "account_type": existing_type,
            "hire_access": existing_hire_access,
        }
        next_path = session.pop("redirect_after_login", None)
        if (
            isinstance(next_path, str)
            and next_path.startswith("/market-research/")
            and (not next_path.startswith("//"))
            and "\n" not in next_path
            and "\r" not in next_path
        ):
            return jsonify({"ok": True, "redirect": next_path})
        return jsonify({"ok": True, "redirect": url_for("auth.studio")})
    except Exception as exc:
        logger.warning("auth session from tokens: %s", exc)
        return jsonify({"ok": False, "error": "invalid_token"}), 401

@bp.route("/logout", methods=["GET", "POST"])
def logout():
    if request.method == "GET":
        return redirect(url_for("jobs"))
    if not csrf_valid():
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("jobs"))
    session.pop("user", None)
    return redirect(url_for("jobs"))

@bp.post("/account/delete")
def account_delete():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.register"))
    if not csrf_valid():
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("auth.profile"))
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        session.pop("user", None)
        flash("Please sign in again.", "error")
        return redirect(url_for("auth.register"))
    delete_confirmation = (request.form.get("confirm_delete") or "").strip()
    if delete_confirmation != "DELETE":
        flash("Type DELETE to confirm account deletion.", "error")
        return redirect(url_for("auth.profile"))
    err = _delete_auth_user(user_id)
    if err:
        flash(err, "error")
        return redirect(url_for("auth.profile"))
    session.pop("user", None)
    flash("Your account has been deleted.", "success")
    return redirect(url_for("jobs"))

@bp.get("/studio")
def studio():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.register"))
    user_id = str(user.get("id") or "").strip()
    email = (user.get("email") or "").strip()
    subs = get_user_subscriptions(user_id) if user_id else {}
    api_access_sub = subs.get("api_access")
    api_key_panel = None
    if email:
        key_rec = get_api_key_by_email(email)
        if key_rec:
            api_key_panel = {
                "key_prefix": key_rec.get("key_prefix"),
                "is_active": bool(key_rec.get("is_active")),
                "tier": key_rec.get("tier") or "",
                "monthly_limit": key_rec.get("monthly_limit"),
                "daily_limit": key_rec.get("daily_limit"),
            }
    return render_template(
        "studio.html",
        user=user,
        subs=subs,
        api_access_sub=api_access_sub,
        api_key_panel=api_key_panel,
    )

@bp.get("/docs/api")
def docs_api():
    """Public developer reference for the Catalitium HTTP API."""
    return render_template("docs_api.html")

@bp.route("/profile", methods=["GET", "POST"])
def profile():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.register"))
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        session.pop("user", None)
        flash("Please sign in again.", "error")
        return redirect(url_for("auth.register"))
    if request.method == "GET":
        profile_data, err = _get_user_profile_metadata(user_id)
        if err and err != "Auth service unavailable.":
            flash(err, "error")
        return render_template("profile.html", user=user, profile=profile_data)
    if not csrf_valid():
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("auth.profile"))
    payload = {field: (request.form.get(field) or "").strip() for field in _PROFILE_FIELDS}
    err = _save_user_profile_metadata(user_id, payload)
    if err:
        flash(err, "error")
        return render_template("profile.html", user=user, profile=_clean_profile_data(payload)), 503 if "unavailable" in err.lower() else 400
    flash("Profile updated.", "success")
    return redirect(url_for("auth.profile"))

@bp.get("/hire")
def hire():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.register"))
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        session.pop("user", None)
        return redirect(url_for("auth.register"))
    hire_data, err = _get_hire_metadata(user_id)
    if err and err != "Auth service unavailable.":
        flash(err, "error")
    account_type = hire_data.get("account_type", "candidate")
    hire_access = bool(hire_data.get("hire_access"))
    session["user"]["account_type"] = account_type
    session["user"]["hire_access"] = hire_access
    if not _is_hire_eligible(account_type, hire_access):
        flash("Complete your company setup to access Hire.", "error")
        return redirect(url_for("auth.hire_onboarding"))
    return render_template("hire.html", user=user, hire=hire_data)

@bp.get("/post-job")
def post_job_form():
    """Full-page job posting form for authenticated recruiters/companies."""
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.register"))

    account_type = (user.get("account_type") or "").lower()
    hire_access = bool(user.get("hire_access"))

    if not _is_hire_eligible(account_type, hire_access):
        flash(
            "Job posting is available for recruiter and company accounts. "
            "Complete your company setup to continue.",
            "error",
        )
        return redirect(url_for("auth.hire_onboarding"))

    user_id = str(user.get("id") or "").strip()
    if not user_id:
        session.pop("user", None)
        return redirect(url_for("auth.register"))

    hire_data, err = _get_hire_metadata(user_id)
    if err and err != "Auth service unavailable.":
        flash(err, "error")
    return render_template("post_job_form.html", user=user, hire=hire_data)

@bp.route("/hire/onboarding", methods=["GET", "POST"])
def hire_onboarding():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.register"))
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        session.pop("user", None)
        return redirect(url_for("auth.register"))
    if request.method == "GET":
        hire_data, err = _get_hire_metadata(user_id)
        if err and err != "Auth service unavailable.":
            flash(err, "error")
        return render_template("hire_onboarding.html", user=user, hire=hire_data)
    if not csrf_valid():
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("auth.hire_onboarding"))
    account_type = _normalize_account_type(request.form.get("account_type", "company"))
    payload = {field: request.form.get(field) or "" for field in _HIRE_FIELDS}
    cleaned = _clean_hire_data(payload)
    if account_type not in _HIRE_ACCOUNT_TYPES:
        flash("Select recruiter or company account type.", "error")
        return render_template("hire_onboarding.html", user=user, hire={**cleaned, "account_type": account_type}), 400
    if len(cleaned["company_name"]) < 2:
        flash("Please enter a valid company name.", "error")
        return render_template("hire_onboarding.html", user=user, hire={**cleaned, "account_type": account_type}), 400
    err = _update_auth_user_metadata(user_id, {**cleaned, "account_type": account_type, "hire_access": True})
    if err:
        flash(err, "error")
        return render_template("hire_onboarding.html", user=user, hire={**cleaned, "account_type": account_type}), 503 if "unavailable" in err.lower() else 400
    session["user"]["account_type"] = account_type
    session["user"]["hire_access"] = True
    flash("Company profile saved. Welcome to Hire.", "success")
    return redirect(url_for("auth.hire"))
