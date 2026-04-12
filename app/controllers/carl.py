"""Carl CV demo, market research hub, and legacy redirects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from ..config import CARL_CHAT_MAX_MESSAGE_CHARS, CARL_CHAT_MAX_TURNS
from ..integrations.carl_mock_analysis import (
    build_mock_analysis,
    carl_effective_user_message,
    generate_chat_reply,
    is_carl_message_grounded,
)
from ..market_reports_data import REPORTS
from ..models.cv import CVExtractionError, extract_cv_from_upload, normalize_cv_text
from ..models.db import SUPABASE_URL, logger, upsert_profile_cv_extract
from ..models.identity import get_user_subscriptions
from ..utils import api_error_response, api_success_response, csrf_valid

bp = Blueprint("carl", __name__)


def _mi_tier(user: Optional[Dict]) -> str:
    """Return the user's active Market Intelligence tier: 'pro', 'premium', or 'free'."""
    if not user:
        return "free"
    subs = get_user_subscriptions(user.get("id", ""))
    mi = subs.get("market_intelligence")
    if mi and mi.get("status") == "active" and mi.get("tier") in ("premium", "pro"):
        return mi["tier"]
    return "free"


@bp.get("/resources")
def resources():
    """Redirect legacy /resources to the unified Market Research hub."""
    return redirect(url_for("carl.market_research_index"), 301)


@bp.get("/market-research")
def market_research_index():
    """Market Research hub: lists all published reports."""
    user = session.get("user")
    mi_tier = _mi_tier(user)
    return render_template(
        "market_research_index.html",
        reports=REPORTS,
        mi_tier=mi_tier,
        user=user,
    )


@bp.get("/troy")
def troy_redirect_carl():
    """Legacy path; Carl lives at ``/carl``."""
    return redirect(url_for("carl.carl_dashboard"), code=301)


@bp.get("/carl")
def carl_dashboard():
    """Render Carl CV dashboard demo page."""
    if not session.get("user"):
        session["redirect_after_login"] = url_for("carl.carl_dashboard")
        flash("Sign in to use Carl.", "info")
        return redirect(url_for("register"))
    return render_template("carl.html", wide_layout=True)


@bp.post("/carl/analyze")
def carl_analyze():
    """Accept CV upload/text fallback and return deterministic mock analysis."""
    if not session.get("user"):
        return api_error_response("login_required", "Sign in to analyze your CV in Carl.", 401)
    if not csrf_valid():
        return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)

    upload = request.files.get("cv_file")
    text_fallback = (request.form.get("cv_text") or "").strip()
    if not upload and not text_fallback:
        return api_error_response("missing_cv_input", "Upload a PDF/DOCX file or paste CV text.", 400)

    source: Dict[str, Any] = {}
    try:
        if upload and (upload.filename or "").strip():
            extracted = extract_cv_from_upload(upload)
            cv_text = extracted.text
            source = {
                "inputType": "file",
                "filename": extracted.filename,
                "extension": extracted.extension,
                "byteSize": extracted.byte_size,
                "truncated": extracted.truncated,
            }
        else:
            cv_text = normalize_cv_text(text_fallback)
            source = {
                "inputType": "text",
                "filename": "pasted_cv_text",
                "extension": "txt",
                "byteSize": len(cv_text.encode("utf-8")),
                "truncated": len(cv_text) >= 50_000,
            }
    except CVExtractionError as exc:
        return api_error_response(exc.code, exc.message, exc.status)

    analysis = build_mock_analysis(cv_text, file_label=source.get("filename", "uploaded_cv"))
    overview = analysis.get("overview") or {}
    skills_radar = analysis.get("skillsRadar") or []
    ats_block = analysis.get("atsScore") or {}
    chat_ctx = analysis.get("chatContext") or {}

    saved_at_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    carl_snapshot = {
        "headline": str(overview.get("headline") or ""),
        "persona": str(overview.get("persona") or ""),
        "level": str(overview.get("level") or ""),
        "atsScore": int(ats_block.get("score") or 0),
        "keywordCoverage": int(ats_block.get("keywordCoverage") or 0),
        "topSkillNames": [str(s.get("skill") or "") for s in skills_radar[:3] if s.get("skill")],
        "saved_at": saved_at_iso,
    }
    persist_meta: Dict[str, Any] = {**source, "carl": carl_snapshot}

    user = session.get("user") or {}
    user_id = user.get("id")
    profile_sync: Dict[str, Any] = {"status": "skipped", "message": None, "saved_at": None}
    if not user_id or not SUPABASE_URL:
        profile_sync["message"] = "Database not configured or missing user."
    else:
        try:
            saved = upsert_profile_cv_extract(
                str(user_id),
                cv_text,
                persist_meta,
                email=str(user.get("email") or "").strip() or None,
            )
            if saved == "ok":
                logger.debug("Carl: CV text persisted to profiles for user %s", str(user_id)[:8])
                profile_sync = {"status": "saved", "message": None, "saved_at": saved_at_iso}
            else:
                logger.warning("Carl: profile CV not persisted (status=%s)", saved)
                profile_sync = {
                    "status": "error",
                    "message": "Could not write to your profile row.",
                    "saved_at": None,
                }
        except Exception as exc:
            logger.warning("profile cv upsert skipped: %s", exc, exc_info=True)
            profile_sync = {
                "status": "error",
                "message": "Profile sync failed unexpectedly.",
                "saved_at": None,
            }

    terminal_logs = list(analysis.get("terminalLogs") or [])
    if profile_sync.get("status") == "saved":
        terminal_logs.append("[Carl] supabase: profile cv_meta updated (cv + carl snapshot).")
    elif profile_sync.get("status") == "error":
        terminal_logs.append("[Carl] supabase: profile sync failed (see server logs).")
    else:
        terminal_logs.append("[Carl] supabase: profile sync skipped (no database or user).")
    analysis["terminalLogs"] = terminal_logs

    session["carl_chat_context"] = {
        "summary": chat_ctx.get("summary", ""),
        "missingKeywords": ats_block.get("missingKeywords", []),
        "matchedKeywords": ats_block.get("matchedKeywords", []),
        "suggestedPrompts": chat_ctx.get("suggestedPrompts", []),
        "persona": overview.get("persona", ""),
        "level": overview.get("level", ""),
        "headline": overview.get("headline", ""),
        "fileLabel": str(source.get("filename") or "uploaded_cv"),
        "topSkillNames": [str(s.get("skill") or "") for s in skills_radar[:5] if s.get("skill")],
    }
    session["carl_chat_turns"] = 0
    session.modified = True
    return api_success_response(
        {
            "analysis": analysis,
            "source": source,
            "profile_sync": profile_sync,
        }
    )


@bp.post("/carl/chat")
def carl_chat():
    """Return a rule-based mock chat reply for Carl dashboard."""
    if not session.get("user"):
        return api_error_response("login_required", "Sign in to use Talk to Carl.", 401)
    if not csrf_valid():
        return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)

    session_ctx = session.get("carl_chat_context") or {}
    if not session_ctx:
        return api_error_response("carl_session_stale", "Analyze a CV first, then chat about that pass.", 400)

    turns = int(session.get("carl_chat_turns") or 0)
    if turns >= CARL_CHAT_MAX_TURNS:
        return api_success_response(
            {
                "reply": (
                    "You have used all free Talk to Carl prompts for this CV pass. "
                    "Unlock the Jobs API on Pricing or review integration on Developers."
                ),
                "chat_limit_reached": True,
                "cta": {
                    "developers": url_for("developers"),
                    "pricing": url_for("payments.pricing"),
                },
            }
        )

    payload = request.get_json(silent=True) or {}
    raw_message = str(payload.get("message") or "").strip()
    has_prompt_id = "prompt_id" in payload
    prompt_id: Optional[int] = None
    if has_prompt_id:
        try:
            prompt_id = int(payload.get("prompt_id"))
        except (TypeError, ValueError):
            return api_error_response("invalid_prompt_id", "Invalid prompt selection.", 400)

    effective_message, pe_err = carl_effective_user_message(
        raw_message, session_ctx, prompt_id=prompt_id if has_prompt_id else None
    )
    if pe_err == "invalid_prompt_id":
        return api_error_response("invalid_prompt_id", "Invalid prompt selection.", 400)
    if not effective_message:
        return api_error_response("invalid_message", "Please write a message for Carl chat.", 400)
    if len(effective_message) > CARL_CHAT_MAX_MESSAGE_CHARS:
        return api_error_response(
            "message_too_long",
            f"Keep messages under {CARL_CHAT_MAX_MESSAGE_CHARS} characters for this demo.",
            400,
        )

    if not is_carl_message_grounded(
        effective_message,
        session_ctx,
        prompt_id=prompt_id if has_prompt_id else None,
    ):
        return api_error_response(
            "chat_not_grounded",
            "Ask about this CV pass using a suggested chip or words from your analysis (keywords, role, file name).",
            400,
        )

    merged_context = {
        "summary": str(session_ctx.get("summary") or ""),
        "missingKeywords": session_ctx.get("missingKeywords") or [],
        "persona": str(session_ctx.get("persona") or ""),
        "level": str(session_ctx.get("level") or ""),
        "headline": str(session_ctx.get("headline") or ""),
        "fileLabel": str(session_ctx.get("fileLabel") or ""),
        "topSkillNames": session_ctx.get("topSkillNames") or [],
    }
    reply = generate_chat_reply(effective_message, merged_context)
    new_turns = turns + 1
    session["carl_chat_turns"] = new_turns
    session.modified = True
    out: Dict[str, Any] = {"reply": reply}
    if new_turns >= CARL_CHAT_MAX_TURNS:
        out["chat_limit_reached"] = True
        out["cta"] = {
            "developers": url_for("developers"),
            "pricing": url_for("payments.pricing"),
        }
    return api_success_response(out)


@bp.get("/market-research/<slug>")
def market_research_report(slug: str):
    """Individual report landing page (fully SSR'd for SEO)."""
    report = next((r for r in REPORTS if r["slug"] == slug), None)
    if not report:
        abort(404)
    user = session.get("user")
    if not user:
        session["redirect_after_login"] = request.path
        flash("Sign in to read this report.", "info")
        return redirect(url_for("register"))
    mi_tier = _mi_tier(user)
    return render_template(
        report.get("template", "reports/report.html"),
        report=report,
        mi_tier=mi_tier,
        user=user,
    )
