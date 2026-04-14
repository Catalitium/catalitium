"""Carl4B2B: employer-facing hiring snapshot from the indexed job catalog only."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse, urlunparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..config import (
    CARL_CHAT_MAX_MESSAGE_CHARS,
    CARL_CHAT_MAX_REPLY_CHARS,
    CARL_CHAT_MAX_TURNS,
)
from ..models.catalog import Job
from ..models.db import SUPABASE_URL, get_db, logger, upsert_profile_carl4b2b_analysis
from ..utils import (
    api_error_response,
    api_success_response,
    csrf_valid,
    normalize_country,
    normalize_title,
)

bp = Blueprint("carl4b2b", __name__, url_prefix="/carl/b2b")

_MAX_LINE = 140
_SAMPLE_CAP = 400

# Default catalog title family when the user only supplies a company URL (bounded search).
_DEFAULT_TITLE_FAMILY = "software"

# Last-label TLD → country hint string for ``normalize_country`` (best-effort).
_TLD_COUNTRY_RAW: Dict[str, str] = {
    "de": "germany",
    "at": "austria",
    "ch": "switzerland",
    "fr": "france",
    "uk": "uk",
    "nl": "netherlands",
    "es": "spain",
    "it": "italy",
    "be": "belgium",
    "pl": "poland",
    "cz": "czech republic",
    "se": "sweden",
    "no": "norway",
    "dk": "denmark",
    "ie": "ireland",
    "pt": "portugal",
    "fi": "finland",
    "in": "india",
    "jp": "japan",
    "au": "australia",
    "ca": "canada",
    "us": "united states",
    "br": "brazil",
    "mx": "mexico",
}


def _brand_token_from_host(host: str) -> str:
    """Heuristic: company name segment from hostname (substring match on catalog company_name)."""
    h = (host or "").lower().strip().rstrip(".")
    if h.startswith("www."):
        h = h[4:]
    parts = [p for p in h.split(".") if p]
    if not parts:
        return ""
    if len(parts) >= 3:
        return parts[-2]
    return parts[0]


def _country_raw_hint_from_host(host: str) -> str:
    h = (host or "").lower().strip().rstrip(".")
    parts = h.split(".")
    if len(parts) >= 3 and parts[-2] == "co" and parts[-1] == "uk":
        return "uk"
    tld = parts[-1] if parts else ""
    return _TLD_COUNTRY_RAW.get(tld, "")


def parse_company_url_for_market_map(raw: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Return ``(canonical_url, title_raw, country_raw, exclude_company, error_code)``.

    ``error_code`` is ``invalid_company_url`` when the string is not a usable http(s) URL with a host.
    """
    s = (raw or "").strip()
    if not s:
        return None, None, None, None, "invalid_company_url"
    if "://" not in s:
        s = "https://" + s
    parsed = urlparse(s)
    if parsed.scheme not in ("http", "https"):
        return None, None, None, None, "invalid_company_url"
    netloc = (parsed.netloc or "").strip()
    if not netloc:
        return None, None, None, None, "invalid_company_url"
    if "@" in netloc:
        netloc = netloc.split("@")[-1]
    netloc = netloc.lower()
    path = parsed.path or ""
    canonical = urlunparse((parsed.scheme, netloc, path, "", parsed.query, parsed.fragment))
    if not path:
        canonical = f"{parsed.scheme}://{netloc}/"

    exclude = _brand_token_from_host(netloc)
    country_raw = _country_raw_hint_from_host(netloc)
    return canonical, _DEFAULT_TITLE_FAMILY, country_raw, exclude, None


def _truncate(text: str, max_len: int) -> str:
    s = (text or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 1)].rstrip() + "…"


def _kw_join(words: Sequence[str], limit: int, empty: str = "none") -> str:
    if not words:
        return empty
    return ", ".join([str(w) for w in words[:limit] if str(w).strip()])


def build_market_map_analysis(
    *,
    title_raw: str,
    country_raw: str,
    exclude_company: str,
    meta: Dict[str, Any],
) -> dict[str, Any]:
    """Aggregate a capped ``Job.search`` sample into a Carl-shaped dashboard JSON."""
    title_q = normalize_title(title_raw or "")
    country_q = normalize_country(country_raw or "")
    exclude = (exclude_company or "").strip().lower()

    total_catalog = int(
        Job.count(title=title_q or None, country=country_q or None)
    )
    rows: List[Dict[str, Any]] = Job.search(
        title=title_q or None,
        country=country_q or None,
        limit=_SAMPLE_CAP,
        offset=0,
    )

    comp_counts: Counter[str] = Counter()
    for r in rows:
        name = (r.get("company_name") or "").strip() or "Unknown"
        if exclude and exclude in name.lower():
            continue
        comp_counts[name] += 1

    top_pairs = comp_counts.most_common(24)
    top_names = [n for n, _ in top_pairs[:12]]
    distinct = len(comp_counts)
    sample_n = len(rows)

    saturation = int(
        min(
            99,
            max(
                18,
                round(28 + 14 * math.log1p(total_catalog) + min(25, distinct)),
            ),
        )
    )
    diversity_pct = int(min(100, round(100 * distinct / max(1, sample_n))))

    top_companies = [
        {
            "name": n,
            "reason": f"{c} postings in catalog sample · indexed titles only",
        }
        for n, c in top_pairs[:8]
    ]
    niche_pool = [(n, c) for n, c in top_pairs if c == 1][:6]
    niche_companies = [
        {"name": n, "reason": "Low-volume hirer in this sample; treat as directional."}
        for n, _ in niche_pool
    ]

    job_cards: List[Dict[str, str]] = []
    for r in rows[:8]:
        if exclude and exclude in str(r.get("company_name") or "").lower():
            continue
        job_cards.append(
            {
                "title": str(r.get("job_title") or "Role"),
                "company": str(r.get("company_name") or "—"),
                "location": str(r.get("location") or r.get("city") or r.get("country") or "—"),
                "link": str(r.get("link") or "/jobs"),
            }
        )

    skills_radar = [
        {"skill": n, "score": int(min(99, 18 + c * 4))}
        for n, c in top_pairs[:10]
    ]

    headline = (
        f"Hiring intensity: “{title_q or 'open titles'}” in {country_q or 'catalog geography'}"
    )
    persona = "Indexed job market"
    level = f"{total_catalog} postings (catalog) · sample {sample_n} rows"
    strengths = [
        f"Top hirer in sample: {top_names[0]}" if top_names else "Sparse matches for this filter.",
        f"{distinct} distinct employers in the capped sample.",
    ]
    risk_flags = [
        "Signals come from Catalitium’s indexed job catalog, not a legal market definition.",
        f"Sample capped at {_SAMPLE_CAP} rows; company strings can be noisy or duplicated.",
        "Country/title filters mirror public job search normalization.",
    ]
    quick_wins = [
        "Compare your own reqs to top posting titles in this band for wording drift.",
        "If you excluded “our company”, sanity-check the string so you do not hide related brands.",
        "Pair this view with recruiter outreach, not as sole sourcing truth.",
    ]

    overview: Dict[str, Any] = {
        "headline": headline,
        "persona": persona,
        "level": level,
        "fitSummary": _truncate(
            "Lead-recruiter view: who is posting, how concentrated hiring is, and how saturated "
            "the indexed slice looks for your filters.",
            350,
        ),
        "confidence": int(min(94, 58 + (distinct % 28))),
        "wordCount": sample_n,
        "signalScores": {
            "structure": int(min(96, 42 + min(52, distinct * 2))),
            "keywords": saturation,
            "impact": int(min(96, 36 + min(58, total_catalog % 72))),
            "narrative": int(min(96, 48 + (total_catalog % 35))),
        },
        "premiumSignals": {
            "leadership": int(min(95, 40 + len(top_names) * 4)),
            "roleMatch": int(min(95, 35 + diversity_pct // 2)),
            "evidenceDensity": int(min(95, 30 + min(60, sample_n // 6))),
        },
    }

    matched_kw = top_names[:6] if top_names else ["—"]
    missing_kw: List[str] = []
    if distinct < 5:
        missing_kw.append("more_posting_volume")

    chat_summary = _truncate(
        f"Catalog pass for {title_q or 'any title'} / {country_q or 'any country'}: "
        f"{total_catalog} postings counted, {distinct} employers in the {_SAMPLE_CAP}-row sample. "
        f"Top hirer: {top_names[0] if top_names else 'n/a'}.",
        350,
    )
    suggested_prompts = [
        "What does market saturation mean for this catalog slice?",
        "Who are the heaviest hiring competitors in the sample?",
        "How should we interpret catalog limits when briefing leadership?",
    ]

    terminal_logs = [
        _truncate("[Carl4B2B] catalog: resolving title/country filters", _MAX_LINE),
        _truncate(f"[Carl4B2B] count: total postings = {total_catalog}", _MAX_LINE),
        _truncate(f"[Carl4B2B] sample: pulled {sample_n} rows (cap {_SAMPLE_CAP})", _MAX_LINE),
        _truncate(f"[Carl4B2B] rollup: {distinct} distinct company_name values", _MAX_LINE),
        _truncate(f"[Carl4B2B] leaders: {_kw_join(top_names, 5)}", _MAX_LINE),
        _truncate(f"[Carl4B2B] meta: exclude='{exclude or '—'}' url={meta.get('business_url') or '—'}", _MAX_LINE),
        "[Carl4B2B] synthesis: dashboard payload assembled",
    ]

    analysis: Dict[str, Any] = {
        "overview": overview,
        "documents": [
            {
                "title": "Market query",
                "subtitle": f"{title_q or '—'} · {country_q or '—'}",
                "badge": "Catalog",
            }
        ],
        "actionFeed": [
            {
                "title": "Calibrate the filter",
                "subtitle": "Tighten title tokens to reduce noise.",
                "detail": "Try a role family plus a single country code to keep competitors comparable.",
            },
            {
                "title": "Watch duplicate employers",
                "subtitle": "Subsidiaries may appear under different strings.",
                "detail": "Use exclude string only for obvious self-matches; legal entity graphs are out of scope.",
            },
        ],
        "skillsRadar": skills_radar,
        "strengths": strengths,
        "experienceTimeline": [
            {
                "period": "Sample",
                "role": "Posting concentration",
                "impact": f"{_kw_join([f'{n} ({c})' for n, c in top_pairs[:3]], 3, 'n/a')}",
            }
        ],
        "atsScore": {
            "score": saturation,
            "keywordCoverage": diversity_pct,
            "matchedKeywords": matched_kw,
            "missingKeywords": missing_kw,
        },
        "riskFlags": risk_flags,
        "quickWins": quick_wins,
        "terminalLogs": terminal_logs,
        "chatContext": {
            "summary": chat_summary,
            "suggestedPrompts": suggested_prompts,
        },
        "matches": {
            "jobs": job_cards,
            "top_companies": top_companies,
            "niche_companies": niche_companies,
        },
        "marketMeta": {
            "title_q": title_q,
            "country_q": country_q,
            "exclude_company": exclude_company.strip(),
            "sample_rows": sample_n,
            "total_count": total_catalog,
            "business_url": (meta.get("business_url") or "").strip(),
            "company_email": (meta.get("company_email") or "").strip(),
            "inferred_from_url": bool(meta.get("inferred_from_url")),
            "inferred_title_family": (meta.get("inferred_title_family") or "").strip(),
        },
    }
    return analysis


def normalize_carl4b2b_user_message(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def is_carl4b2b_message_grounded(
    message: str,
    snapshot: dict[str, Any],
    *,
    prompt_id: Optional[int] = None,
) -> bool:
    prompts_raw = snapshot.get("suggestedPrompts") or []
    prompts = [str(p) for p in prompts_raw if str(p).strip()]
    if prompt_id is not None:
        if isinstance(prompt_id, int) and 0 <= prompt_id < len(prompts):
            return True
        return False

    msg_norm = normalize_carl4b2b_user_message(message)
    if not msg_norm:
        return False
    msg_key = msg_norm.casefold()
    for p in prompts:
        if msg_key == normalize_carl4b2b_user_message(p).casefold():
            return True

    ml = msg_norm.lower()
    catalog_terms = (
        "saturation",
        "catalog",
        "competitor",
        "market",
        "indexed",
        "posting",
        "employer",
        "hiring",
        "sample",
    )
    if any(t in ml for t in catalog_terms):
        return True

    def _kw_hits(keys: Sequence[str]) -> bool:
        for k in keys:
            kk = str(k).strip().lower()
            if len(kk) >= 2 and kk in ml:
                return True
        return False

    if _kw_hits(snapshot.get("missingKeywords") or []):
        return True
    if _kw_hits(snapshot.get("matchedKeywords") or []):
        return True
    if _kw_hits(snapshot.get("topSkillNames") or []):
        return True
    if _kw_hits(snapshot.get("competitorNames") or []):
        return True

    level = str(snapshot.get("level") or "").strip().lower()
    if level and level in ml:
        return True
    persona = str(snapshot.get("persona") or "").strip().lower()
    if persona and persona in ml:
        return True

    tq = str(snapshot.get("titleQuery") or "").strip().lower()
    if len(tq) >= 3 and tq in ml:
        return True
    cq = str(snapshot.get("countryQuery") or "").strip().lower()
    if len(cq) >= 2 and cq in ml:
        return True

    headline = str(snapshot.get("headline") or "")
    for tok in re.findall(r"[a-z0-9]+", headline.lower()):
        if len(tok) >= 4 and tok in ml:
            return True

    return False


def carl4b2b_effective_user_message(
    message: str,
    snapshot: dict[str, Any],
    *,
    prompt_id: Optional[int] = None,
) -> tuple[str, Optional[str]]:
    prompts_raw = snapshot.get("suggestedPrompts") or []
    prompts = [str(p) for p in prompts_raw if str(p).strip()]
    if prompt_id is not None:
        if not isinstance(prompt_id, int) or not (0 <= prompt_id < len(prompts)):
            return "", "invalid_prompt_id"
        return prompts[prompt_id], None
    return normalize_carl4b2b_user_message(message), None


def generate_carl4b2b_chat_reply(message: str, chat_context: dict[str, Any]) -> str:
    cap = CARL_CHAT_MAX_REPLY_CHARS

    def _out(s: str) -> str:
        return _truncate(s, cap)

    prompt = (message or "").strip().lower()
    if not prompt:
        return _out("Ask about saturation, competitors, or how to read this catalog slice.")

    summary = str(chat_context.get("summary") or "").strip()
    headline = str(chat_context.get("headline") or "").strip()
    competitors = chat_context.get("competitorNames") or []

    if "saturation" in prompt:
        return _out(
            "Saturation here is a heuristic from posting volume and employer diversity in the "
            "indexed slice — not a legal market share."
        )
    if "competitor" in prompt or "hir" in prompt:
        if competitors:
            return _out(
                "Heaviest hirers in this sample: "
                + ", ".join(str(n) for n in competitors[:5] if n)
                + ". Treat subsidiaries and string variants as separate rows."
            )
        return _out("No strong competitor cluster in this sample; widen title or geography slightly.")
    if "catalog" in prompt or "limit" in prompt or "sample" in prompt:
        return _out(
            "We cap the rolling sample and always label totals from COUNT vs. the pulled rows. "
            "Use this as directional intelligence alongside your own ATS and CRM."
        )
    if any(prompt.startswith(h) for h in ("hi", "hello", "hey", "help", "thanks")):
        return _out("Carl4B2B is grounded on this catalog pass — ask about saturation, competitors, or data limits.")

    return _out(summary or "Ask how to read saturation, competitors, or catalog limits for this pass.")


def _chat_snapshot_from_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    overview = analysis.get("overview") or {}
    chat_ctx = analysis.get("chatContext") or {}
    ats_block = analysis.get("atsScore") or {}
    skills_radar = analysis.get("skillsRadar") or []
    matches = analysis.get("matches") or {}
    comps = matches.get("top_companies") or []
    comp_names = [str(c.get("name") or "") for c in comps if c.get("name")]
    meta = analysis.get("marketMeta") or {}
    return {
        "summary": str(chat_ctx.get("summary") or ""),
        "missingKeywords": list(ats_block.get("missingKeywords") or []),
        "matchedKeywords": list(ats_block.get("matchedKeywords") or []),
        "suggestedPrompts": list(chat_ctx.get("suggestedPrompts") or []),
        "persona": str(overview.get("persona") or ""),
        "level": str(overview.get("level") or ""),
        "headline": str(overview.get("headline") or ""),
        "fileLabel": "market_query",
        "topSkillNames": [str(s.get("skill") or "") for s in skills_radar[:5] if s.get("skill")],
        "competitorNames": comp_names,
        "titleQuery": str(meta.get("title_q") or ""),
        "countryQuery": str(meta.get("country_q") or ""),
    }


@bp.get("")
def carl4b2b_dashboard():
    user = session.get("user")
    if not user:
        session["redirect_after_login"] = url_for("carl4b2b.carl4b2b_dashboard")
        flash("Sign in to use Carl for companies.", "info")
        return redirect(url_for("auth.register"))

    uid = user.get("id")
    preloaded = None
    if uid and SUPABASE_URL:
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute(
                    "SELECT last_carl4b2b_analysis FROM profiles WHERE id = %s::uuid",
                    (uid,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    preloaded = row[0]
        except Exception as exc:
            logger.warning("Carl4B2B: failed to preload profile analysis for %s: %s", uid, exc)

    if isinstance(preloaded, dict) and preloaded.get("overview"):
        session["carl4b2b_chat_context"] = _chat_snapshot_from_analysis(preloaded)
        session["carl4b2b_chat_turns"] = 0
        session.modified = True

    return render_template(
        "carl4b2b.html",
        wide_layout=True,
        preloaded_carl4b2b_analysis=preloaded,
    )


@bp.post("/analyze")
def carl4b2b_analyze():
    if not session.get("user"):
        return api_error_response("login_required", "Sign in to run the company market map.", 401)
    if not csrf_valid():
        return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)

    payload = request.get_json(silent=True) or {}
    business_url_in = str(payload.get("business_url") or "").strip()

    if not business_url_in:
        return api_error_response(
            "invalid_company_url",
            "Provide your company or careers page URL.",
            400,
        )

    canonical_url, title_raw, country_raw, exclude_company, url_err = parse_company_url_for_market_map(
        business_url_in
    )
    if url_err:
        return api_error_response(
            "invalid_company_url",
            "Enter a valid http(s) URL with a hostname (e.g. https://yourcompany.com).",
            400,
        )

    company_email = str(payload.get("company_email") or "").strip()

    meta = {
        "business_url": canonical_url or business_url_in,
        "company_email": company_email,
        "inferred_from_url": True,
        "inferred_title_family": _DEFAULT_TITLE_FAMILY,
    }
    analysis = build_market_map_analysis(
        title_raw=title_raw or "",
        country_raw=country_raw or "",
        exclude_company=exclude_company or "",
        meta=meta,
    )

    mm = analysis.get("marketMeta") or {}
    title_q = str(mm.get("title_q") or "")
    country_q = str(mm.get("country_q") or "")
    if len(title_q) < 2 and len(country_q) < 2:
        return api_error_response(
            "invalid_company_url",
            "Could not derive a catalog query from that URL.",
            400,
        )

    pre_logs = [
        _truncate(f"[Carl4B2B] company_url: {canonical_url}", _MAX_LINE),
        _truncate(
            f"[Carl4B2B] inferred: title≈{title_q} country≈{country_q or '—'} exclude≈{(exclude_company or '—').lower()}",
            _MAX_LINE,
        ),
    ]
    analysis["terminalLogs"] = pre_logs + list(analysis.get("terminalLogs") or [])

    user = session.get("user") or {}
    user_id = user.get("id")
    saved_at_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    profile_sync: Dict[str, Any] = {"status": "skipped", "message": None, "saved_at": None}
    if not user_id or not SUPABASE_URL:
        profile_sync["message"] = "Database not configured or missing user."
    else:
        try:
            saved = upsert_profile_carl4b2b_analysis(str(user_id), analysis)
            if saved == "ok":
                profile_sync = {"status": "saved", "message": None, "saved_at": saved_at_iso}
            else:
                profile_sync = {
                    "status": "error",
                    "message": "Could not write B2B snapshot to your profile row.",
                    "saved_at": None,
                }
        except Exception as exc:
            logger.warning("Carl4B2B profile upsert skipped: %s", exc, exc_info=True)
            profile_sync = {
                "status": "error",
                "message": "Profile sync failed unexpectedly.",
                "saved_at": None,
            }

    terminal_logs = list(analysis.get("terminalLogs") or [])
    if profile_sync.get("status") == "saved":
        terminal_logs.append("[Carl4B2B] supabase: last_carl4b2b_analysis updated.")
    elif profile_sync.get("status") == "error":
        terminal_logs.append("[Carl4B2B] supabase: profile sync failed (see server logs).")
    else:
        terminal_logs.append("[Carl4B2B] supabase: profile sync skipped.")
    analysis["terminalLogs"] = terminal_logs

    snap = _chat_snapshot_from_analysis(analysis)
    session["carl4b2b_chat_context"] = snap
    session["carl4b2b_chat_turns"] = 0
    session.modified = True

    source = {
        "inputType": "company_url",
        "title_q": title_q,
        "country_q": country_q,
        "exclude_company": exclude_company or "",
        "business_url": canonical_url or business_url_in,
        "company_email": company_email,
    }

    return api_success_response(
        {
            "analysis": analysis,
            "source": source,
            "profile_sync": profile_sync,
        }
    )


@bp.post("/chat")
def carl4b2b_chat():
    if not session.get("user"):
        return api_error_response("login_required", "Sign in to use company chat.", 401)
    if not csrf_valid():
        return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)

    session_ctx = session.get("carl4b2b_chat_context") or {}
    if not session_ctx:
        return api_error_response(
            "carl4b2b_session_stale",
            "Run a market map first, then chat about that pass.",
            400,
        )

    turns = int(session.get("carl4b2b_chat_turns") or 0)
    if turns >= CARL_CHAT_MAX_TURNS:
        return api_success_response(
            {
                "reply": (
                    "You have used all free prompts for this catalog pass. "
                    "Review pricing or widen your search from the Jobs area."
                ),
                "chat_limit_reached": True,
                "cta": {
                    "developers": url_for("jobs.developers"),
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

    effective_message, pe_err = carl4b2b_effective_user_message(
        raw_message, session_ctx, prompt_id=prompt_id if has_prompt_id else None
    )
    if pe_err == "invalid_prompt_id":
        return api_error_response("invalid_prompt_id", "Invalid prompt selection.", 400)
    if not effective_message:
        return api_error_response("invalid_message", "Please write a message.", 400)
    if len(effective_message) > CARL_CHAT_MAX_MESSAGE_CHARS:
        return api_error_response(
            "message_too_long",
            f"Keep messages under {CARL_CHAT_MAX_MESSAGE_CHARS} characters for this demo.",
            400,
        )

    if not is_carl4b2b_message_grounded(
        effective_message,
        session_ctx,
        prompt_id=prompt_id if has_prompt_id else None,
    ):
        return api_error_response(
            "chat_not_grounded",
            "Ask about this catalog pass using a suggested chip or words from the analysis.",
            400,
        )

    merged_context = {
        "summary": str(session_ctx.get("summary") or ""),
        "headline": str(session_ctx.get("headline") or ""),
        "competitorNames": session_ctx.get("competitorNames") or [],
    }
    reply = generate_carl4b2b_chat_reply(effective_message, merged_context)
    new_turns = turns + 1
    session["carl4b2b_chat_turns"] = new_turns
    session.modified = True
    out: Dict[str, Any] = {"reply": reply}
    if new_turns >= CARL_CHAT_MAX_TURNS:
        out["chat_limit_reached"] = True
        out["cta"] = {
            "developers": url_for("jobs.developers"),
            "pricing": url_for("payments.pricing"),
        }
    return api_success_response(out)
