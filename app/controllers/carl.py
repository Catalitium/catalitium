"""Carl CV demo, market research hub, and legacy redirects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

import hashlib
import random
import re

from ..config import (
    CARL_CHAT_MAX_MESSAGE_CHARS,
    CARL_CHAT_MAX_REPLY_CHARS,
    CARL_CHAT_MAX_TURNS,
)
from ..utils import REPORTS
from ..models.cv import CVExtractionError, extract_cv_from_upload, normalize_cv_text
from ..models.db import SUPABASE_URL, logger, upsert_profile_cv_extract
from ..models.identity import get_user_subscriptions
from ..utils import api_error_response, api_success_response, csrf_valid
from .auth import upload_cv_to_storage

DEFAULT_TARGET_KEYWORDS = [
    "python",
    "sql",
    "aws",
    "docker",
    "kubernetes",
    "leadership",
    "analytics",
    "machine learning",
]

_MAX_LINE = 140
_MAX_SUMMARY = 350
_MAX_SNIPPET = 120


def _truncate(text: str, max_len: int) -> str:
    s = (text or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 1)].rstrip() + "…"


def _cv_snippet(normalized: str, max_len: int = _MAX_SNIPPET) -> str:
    """Single-line excerpt from CV body for terminal (no raw dumps)."""
    line = re.sub(r"\s+", " ", str(normalized or "")).strip()
    return _truncate(line, max_len)


def _kw_join(words: Sequence[str], limit: int, empty: str = "none") -> str:
    if not words:
        return empty
    return ", ".join(words[:limit])


def _build_terminal_logs(
    *,
    file_label: str,
    ats_score: int,
    strengths: list[str],
    risk_flags: list[str],
    word_count: int,
    unique_count: int,
    persona: str,
    level: str,
    years: int,
    top_skills: list[dict[str, Any]],
    matched_keywords: list[str],
    missing_keywords: list[str],
    structure_score: int,
    impact_score: int,
    narrative_score: int,
    narrative_confidence: int,
    normalized: str,
    headline: str,
    jobs: list[dict[str, Any]],
    companies: list[dict[str, Any]],
) -> list[str]:
    """Longer, CV-grounded terminal feed (existing UI streams these lines)."""
    excerpt = _cv_snippet(normalized, _MAX_SNIPPET)
    top3 = top_skills[:3]
    skill_bits = [
        f"{s.get('skill', '?')}={int(s.get('score') or 0)}" for s in top3
    ]
    matched_s = _kw_join(matched_keywords, 8, "none")
    missing_s = _kw_join(missing_keywords, 8, "none")
    logs: list[str] = [
        _truncate(f"[Carl] ingest: {file_label}", _MAX_LINE),
        "[Carl] parser: extracting CV text blocks",
        _truncate(f"[Carl] tokenizer: {word_count} tokens, {unique_count} distinct roots", _MAX_LINE),
        _truncate(f"[Carl] excerpt: {excerpt}", _MAX_LINE),
        _truncate(f"[Carl] role-detect: {level} · {persona}", _MAX_LINE),
        _truncate(f"[Carl] tenure-signal: ~{years}y trajectory (heuristic)", _MAX_LINE),
        _truncate(f"[Carl] skills-ranked: {', '.join(skill_bits)}", _MAX_LINE),
        _truncate(f"[Carl] ats-keywords-hit: {matched_s}", _MAX_LINE),
        _truncate(f"[Carl] ats-keywords-miss: {missing_s}", _MAX_LINE),
        _truncate(f"[Carl] ats-estimator: score={ats_score}", _MAX_LINE),
        _truncate(
            f"[Carl] scorecard: structure={structure_score} impact={impact_score} narrative={narrative_score}",
            _MAX_LINE,
        ),
        _truncate(f"[Carl] confidence: model={narrative_confidence}% (demo)", _MAX_LINE),
        _truncate(f"[Carl] strengths: {strengths[0]}", _MAX_LINE),
    ]
    if len(strengths) > 1:
        logs.append(_truncate(f"[Carl] strengths+: {strengths[1]}", _MAX_LINE))
    if risk_flags:
        logs.append(_truncate(f"[Carl] risk: {risk_flags[0]}", _MAX_LINE))
    
    # Radar logs
    logs.append(_truncate(f"[Carl] market-radar: scanning for {persona} role matches...", _MAX_LINE))
    if jobs:
        role_titles = ", ".join([j.get("title", "") for j in jobs[:2]])
        logs.append(_truncate(f"[Carl] matches: found {len(jobs)} target roles ({role_titles})", _MAX_LINE))
    if companies:
        comp_names = ", ".join([c.get("name", "") for c in companies[:3]])
        logs.append(_truncate(f"[Carl] companies: mapping active tech hubs ({comp_names})", _MAX_LINE))

    logs.append(_truncate(f"[Carl] synthesis: {_truncate(headline, 100)}", _MAX_LINE))
    logs.append("[Carl] ready: dashboard payload assembled")
    return logs


def _build_chat_summary(
    *,
    headline: str,
    persona: str,
    level: str,
    file_label: str,
    matched_keywords: list[str],
    missing_keywords: list[str],
) -> str:
    m2 = _kw_join(matched_keywords, 2, "")
    x2 = _kw_join(missing_keywords, 2, "")
    parts = [
        f"You uploaded {_truncate(file_label, 60)}.",
        f"I read you as a {level} {persona}: {headline}",
    ]
    if m2 and m2 not in ("", "none"):
        parts.append(f"Strong ATS matches already present: {m2}.")
    if x2 and x2 not in ("", "none"):
        parts.append(f"Next leverage: weave {x2} into real project outcomes (metrics + scope).")
    else:
        parts.append("Next leverage: add measurable outcomes (%, $, latency) beside each major role.")
    raw = " ".join(parts)
    return _truncate(raw, _MAX_SUMMARY)


def _build_suggested_prompts(
    missing_keywords: list[str],
    keyword_coverage: int,
) -> list[str]:
    if missing_keywords:
        gap = ", ".join(missing_keywords[:3])
        return [
            f"Where should I add {gap} without keyword stuffing?",
            "Rewrite one experience block for hiring managers in 4 bullets.",
            "What metrics would make my impact undeniable on a first skim?",
        ]
    if keyword_coverage >= 75:
        return [
            "How do I tighten my story so impact reads above the fold?",
            "Which bullets should I cut to reduce noise for recruiters?",
            "What quantified wins should sit in my summary line?",
        ]
    return [
        "How can I increase my ATS score quickly?",
        "Rewrite my profile summary for hiring managers.",
        "What bullet points should I add for impact?",
    ]


def build_mock_analysis(cv_text: str, *, file_label: str = "uploaded_cv") -> dict[str, Any]:
    """Return a deterministic analysis payload based on CV text."""
    normalized = _normalize(cv_text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    seed = int(digest[:12], 16)
    rng = random.Random(seed)

    text_lower = normalized.lower()
    words = [w for w in re.split(r"\W+", text_lower) if w]
    unique_words = set(words)
    years = _infer_years_experience(text_lower)
    level = _infer_level(text_lower, years)
    persona = _infer_persona(text_lower)
    confidence = 74 + (seed % 23)

    top_skills = _rank_skills(text_lower, rng)
    matched_keywords = [k for k in DEFAULT_TARGET_KEYWORDS if k in text_lower]
    missing_keywords = [k for k in DEFAULT_TARGET_KEYWORDS if k not in text_lower][:4]

    keyword_coverage = int(round((len(matched_keywords) / max(1, len(DEFAULT_TARGET_KEYWORDS))) * 100))
    ats_score = min(96, max(42, int(58 + keyword_coverage * 0.35 + len(unique_words) * 0.04)))

    strengths = _build_strengths(top_skills, years, level)
    risk_flags = _build_risk_flags(text_lower, missing_keywords)
    quick_wins = _build_quick_wins(missing_keywords, text_lower)
    timeline = _build_timeline(level, years, rng)

    structure_score = min(100, 48 + min(len(words) // 25, 28))
    impact_score = min(
        100,
        52
        + (18 if "%" in text_lower or "increased" in text_lower or "reduced" in text_lower else 0)
        + min(years * 2, 20),
    )
    narrative_score = min(100, 44 + min(len(unique_words) // 12, 30))
    leadership_score = min(
        100,
        46
        + (18 if any(token in text_lower for token in ("lead", "managed", "owner", "director")) else 0)
        + min(years * 2, 18),
    )
    role_match_score = min(
        100,
        52 + int(ats_score * 0.35) + (10 if persona.lower() in text_lower else 0),
    )
    quantified_hits = len(re.findall(r"\d+(?:\.\d+)?%|\$\d+|\d+\s*(?:ms|sec|minutes|hours|days|x)\b", text_lower))
    evidence_density = min(100, 42 + min(quantified_hits * 8, 42) + min(years, 10))

    headline = f"{level} {persona} profile with {keyword_coverage}% ATS keyword coverage"
    fit_summary = (
        f"CV shows {years}+ years of relevant signal with strongest evidence in "
        f"{', '.join(s['skill'] for s in top_skills[:3])}. "
        f"Pulled from {_truncate(file_label, 80)}."
    )
    fit_summary = _truncate(fit_summary, 280)

    documents = [
        {
            "title": "CV intelligence",
            "subtitle": _truncate(f"Source · {file_label} · Indexed · {len(words)} words", 95),
            "badge": "New",
        },
        {"title": "Skills evidence", "subtitle": f"{len(top_skills)} ranked signals", "badge": "New"},
        {"title": "ATS keyword map", "subtitle": f"{keyword_coverage}% coverage", "badge": None},
        {"title": "Experience arc", "subtitle": f"~{years}y trajectory", "badge": None},
    ]
    gap_preview = ", ".join(missing_keywords[:2]) if missing_keywords else "Strong coverage"
    action_feed = [
        {
            "title": "ATS opportunities",
            "subtitle": gap_preview,
            "detail": risk_flags[0] if risk_flags else "Keep sharpening impact bullets.",
        },
        {
            "title": "Quick wins",
            "subtitle": (quick_wins[0][:72] + "…") if quick_wins and len(quick_wins[0]) > 72 else (quick_wins[0] if quick_wins else "Add metrics to top roles"),
            "detail": quick_wins[1] if len(quick_wins) > 1 else strengths[0],
        },
        {
            "title": "Narrative polish",
            "subtitle": "Summary & positioning",
            "detail": strengths[1] if len(strengths) > 1 else fit_summary[:120],
        },
    ]

    terminal_logs = _build_terminal_logs(
        file_label=file_label,
        ats_score=ats_score,
        strengths=strengths,
        risk_flags=risk_flags,
        word_count=len(words),
        unique_count=len(unique_words),
        persona=persona,
        level=level,
        years=years,
        top_skills=top_skills,
        matched_keywords=matched_keywords,
        missing_keywords=missing_keywords,
        structure_score=structure_score,
        impact_score=impact_score,
        narrative_score=narrative_score,
        narrative_confidence=confidence,
        normalized=normalized,
        headline=headline,
        jobs=[], # Will be populated below
        companies=[] # Will be populated below
    )

    chat_summary = _build_chat_summary(
        headline=headline,
        persona=persona,
        level=level,
        file_label=file_label,
        matched_keywords=matched_keywords,
        missing_keywords=missing_keywords,
    )
    suggested_prompts = _build_suggested_prompts(missing_keywords, keyword_coverage)

    try:
        from ..models.catalog import Job
        real_jobs = Job.search(persona, None, limit=12, offset=0)
    except Exception:
        real_jobs = []

    recommended_jobs = []
    top_companies = []
    niche_companies = []

    if real_jobs:
        for r in real_jobs[:3]:
            recommended_jobs.append({
                "title": r.get("job_title", "Unknown Role"),
                "company": r.get("company_name", "Confidential"),
                "location": r.get("location", "Remote"),
                "link": r.get("link", "#")
            })
        
        comps = set()
        for r in real_jobs:
            c = (r.get("company_name") or "").strip()
            if c and c not in comps:
                comps.add(c)
        clist = list(comps)
        for c in clist[:3]:
            top_companies.append({"name": c, "reason": f"Top volume hiring for {persona}"})
        for c in clist[3:6]:
            niche_companies.append({"name": c, "reason": "Remote-first emerging team"})

    if not recommended_jobs:
        recommended_jobs = [
            {"title": f"Senior {persona}", "company": "TechGlobal", "location": "Remote", "link": "/jobs"},
            {"title": f"{level} {persona}", "company": "DataFlow Systems", "location": "San Francisco", "link": "/jobs"},
            {"title": f"Staff {persona}", "company": "Alpha Innovations", "location": "New York", "link": "/jobs"},
        ]
    if not top_companies:
        top_companies = [
            {"name": "Stripe", "reason": f"Leading compensation for {persona}s"},
            {"name": "Anthropic", "reason": "High demand tier"},
            {"name": "Rippling", "reason": "Aggressive scaling"},
        ]
    if not niche_companies:
        niche_companies = [
            {"name": "Supabase", "reason": "Open-source remote-first culture"},
            {"name": "Vercel", "reason": "Frontend & design focused"},
            {"name": "Linear", "reason": "High product velocity"},
        ]

    # Re-build terminal logs with match context
    terminal_logs = _build_terminal_logs(
        file_label=file_label,
        ats_score=ats_score,
        strengths=strengths,
        risk_flags=risk_flags,
        word_count=len(words),
        unique_count=len(unique_words),
        persona=persona,
        level=level,
        years=years,
        top_skills=top_skills,
        matched_keywords=matched_keywords,
        missing_keywords=missing_keywords,
        structure_score=structure_score,
        impact_score=impact_score,
        narrative_score=narrative_score,
        narrative_confidence=confidence,
        normalized=normalized,
        headline=headline,
        jobs=recommended_jobs,
        companies=top_companies
    )

    return {
        "overview": {
            "persona": persona,
            "level": level,
            "confidence": confidence,
            "headline": headline,
            "fitSummary": fit_summary,
            "wordCount": len(words),
            "signalScores": {
                "structure": structure_score,
                "keywords": keyword_coverage,
                "impact": impact_score,
                "narrative": narrative_score,
            },
            "premiumSignals": {
                "leadership": leadership_score,
                "roleMatch": role_match_score,
                "evidenceDensity": evidence_density,
            },
        },
        "documents": documents,
        "actionFeed": action_feed,
        "skillsRadar": top_skills,
        "strengths": strengths,
        "experienceTimeline": timeline,
        "atsScore": {
            "score": ats_score,
            "keywordCoverage": keyword_coverage,
            "matchedKeywords": matched_keywords[:8],
            "missingKeywords": missing_keywords,
        },
        "riskFlags": risk_flags,
        "quickWins": quick_wins,
        "terminalLogs": terminal_logs,
        "chatContext": {
            "summary": chat_summary,
            "suggestedPrompts": suggested_prompts,
        },
        "matches": {
            "jobs": recommended_jobs,
            "top_companies": top_companies,
            "niche_companies": niche_companies,
        }
    }


def normalize_carl_user_message(text: str) -> str:
    """Collapse whitespace for stable comparisons (chip text vs freeform)."""
    return re.sub(r"\s+", " ", (text or "").strip())


def is_carl_message_grounded(
    message: str,
    snapshot: dict[str, Any],
    *,
    prompt_id: Optional[int] = None,
) -> bool:
    """Return True when the user may spend a Carl chat turn on this input.

    Rules (server-side; document in tests):
    1. ``prompt_id`` is an int in ``[0, len(suggestedPrompts))`` (chip / guided path).
    2. Normalized ``message`` equals one of ``suggestedPrompts`` (case-insensitive).
    3. A ``missingKeywords`` or ``matchedKeywords`` entry appears as a substring of
       ``message.lower()`` (supports multi-word keywords like "machine learning").
    4. A ``topSkillNames`` entry appears in ``message.lower()`` (case-insensitive).
    5. ``level`` or full ``persona`` appears as a substring in ``message.lower()``.
    6. ``fileLabel`` appears as a substring in ``message.lower()``.
    7. Any alphanumeric token of length >= 4 from ``headline`` appears in ``message.lower()``.
    """
    prompts_raw = snapshot.get("suggestedPrompts") or []
    prompts = [str(p) for p in prompts_raw if str(p).strip()]
    if prompt_id is not None:
        if isinstance(prompt_id, int) and 0 <= prompt_id < len(prompts):
            return True
        return False

    msg_norm = normalize_carl_user_message(message)
    if not msg_norm:
        return False
    msg_key = msg_norm.casefold()
    for p in prompts:
        if msg_key == normalize_carl_user_message(p).casefold():
            return True

    ml = msg_norm.lower()

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

    level = str(snapshot.get("level") or "").strip().lower()
    if level and level in ml:
        return True
    persona = str(snapshot.get("persona") or "").strip().lower()
    if persona and persona in ml:
        return True

    file_label = str(snapshot.get("fileLabel") or "").strip().lower()
    if file_label and file_label in ml:
        return True

    headline = str(snapshot.get("headline") or "")
    for tok in re.findall(r"[a-z0-9]+", headline.lower()):
        if len(tok) >= 4 and tok in ml:
            return True

    return False


def carl_effective_user_message(
    message: str,
    snapshot: dict[str, Any],
    *,
    prompt_id: Optional[int] = None,
) -> tuple[str, Optional[str]]:
    """Return (effective_message, error_code). error_code set when prompt_id is invalid."""
    prompts_raw = snapshot.get("suggestedPrompts") or []
    prompts = [str(p) for p in prompts_raw if str(p).strip()]
    if prompt_id is not None:
        if not isinstance(prompt_id, int) or not (0 <= prompt_id < len(prompts)):
            return "", "invalid_prompt_id"
        return prompts[prompt_id], None
    return normalize_carl_user_message(message), None


def generate_chat_reply(message: str, chat_context: dict[str, Any]) -> str:
    """Generate a deterministic rule-based chat reply."""
    cap = CARL_CHAT_MAX_REPLY_CHARS

    def _out(s: str) -> str:
        return _truncate(s, cap)

    prompt = (message or "").strip().lower()
    if not prompt:
        return _out("Share one question about your CV and I will suggest specific improvements.")

    missing_keywords = chat_context.get("missingKeywords") or []
    summary = str(chat_context.get("summary") or "").strip()
    headline = str(chat_context.get("headline") or "").strip()
    persona = str(chat_context.get("persona") or "").strip()
    level = str(chat_context.get("level") or "").strip()
    file_label = str(chat_context.get("fileLabel") or "").strip()
    top_skill_names = chat_context.get("topSkillNames") or []

    if "ats" in prompt or "score" in prompt:
        if missing_keywords:
            return _out(
                "Fast ATS win: include these missing keywords in context-based bullet points: "
                + ", ".join(missing_keywords[:4])
                + "."
            )
        return _out("Your ATS signal is strong. Next gain comes from quantifying outcomes in each experience bullet.")
    if "rewrite" in prompt or "summary" in prompt:
        return _out(
            "Suggested summary: Results-driven professional with a track record of delivering measurable impact, "
            "cross-functional execution, and strong ownership across complex initiatives."
        )
    if "risk" in prompt or "weak" in prompt or "gap" in prompt:
        if missing_keywords:
            return _out("Main risk is keyword coverage gaps in: " + ", ".join(missing_keywords[:3]) + ".")
        return _out("Main risk is low quantified impact. Add metrics, percentages, or revenue/cost outcomes per role.")

    if any(k in prompt for k in ("who am i", "who am i?", "headline", "positioning", "how do i read")):
        if headline and persona and level:
            return _out(
                f"Based on this CV pass: you are signaling {level} {persona}. Headline read: {headline}",
            )
        if persona and level:
            return _out(f"Based on this CV pass: you are signaling {level} {persona}.")

    if "file" in prompt or "upload" in prompt or "pdf" in prompt or "docx" in prompt:
        if file_label:
            return _out(
                f"I anchored this pass on {file_label} - ask about ATS gaps or bullet rewrites tied to that version.",
            )

    if any(
        prompt.startswith(h)
        for h in ("hi", "hello", "hey", "help", "thanks", "thank you")
    ) or prompt in ("help", "help me", "?", "what can you do"):
        tail = ""
        if missing_keywords:
            tail = f" Start with missing terms: {', '.join(missing_keywords[:3])}."
        elif top_skill_names:
            names = ", ".join(str(n) for n in top_skill_names[:3] if n)
            if names:
                tail = f" Strongest ranked signals on this pass: {names}."
        elif headline:
            tail = f" {headline}"
        base = "I am Carl on this CV snapshot - ask about ATS, gaps, or a rewrite."
        return _out(base + tail)

    # Scope Guardrail for out of bounds questions
    carl_topics = ("rewrite", "resume", "cv", "ats", "interview", "score", "skill", "job", "career", "gap", "bullet", "metrics", "impact", "summary")
    if text := prompt.split():
        # A simple check: if the prompt doesn't trigger any heuristics above and doesn't contain CV keywords
        if not any(t in prompt for t in carl_topics):
            return _out(f"I specialize in CV coaching and ATS optimization. Let's stay focused on your {level} {persona} profile!")

    out = summary or "I analyzed your CV. Ask about ATS, bullet rewriting, or risk flags for concrete guidance."
    return _out(out)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _infer_years_experience(text_lower: str) -> int:
    years_found = []
    for match in re.findall(r"(\d{1,2})\+?\s*(?:years?|yrs?)", text_lower):
        try:
            years_found.append(int(match))
        except ValueError:
            continue
    if years_found:
        return min(25, max(years_found))
    return 2 if "intern" in text_lower else 5


def _infer_level(text_lower: str, years: int) -> str:
    if "principal" in text_lower or "staff" in text_lower:
        return "Principal"
    if "lead" in text_lower or years >= 10:
        return "Senior"
    if "junior" in text_lower or "intern" in text_lower or years <= 2:
        return "Junior"
    return "Mid-level"


def _infer_persona(text_lower: str) -> str:
    if "data" in text_lower and "scient" in text_lower:
        return "Data Scientist"
    if "product" in text_lower and "manager" in text_lower:
        return "Product Manager"
    if "devops" in text_lower or "sre" in text_lower:
        return "Platform Engineer"
    if "frontend" in text_lower:
        return "Frontend Engineer"
    if "backend" in text_lower:
        return "Backend Engineer"
    return "Software Engineer"


def _rank_skills(text_lower: str, rng: random.Random) -> list[dict[str, Any]]:
    catalog = [
        "Python",
        "SQL",
        "AWS",
        "Docker",
        "Kubernetes",
        "Leadership",
        "Communication",
        "Data Analysis",
        "Machine Learning",
        "System Design",
    ]
    ranked = []
    for skill in catalog:
        key = skill.lower()
        if key in text_lower:
            base = 65
            bonus = rng.randint(8, 32)
        else:
            base = 15
            bonus = rng.randint(0, 10)
        ranked.append({"skill": skill, "score": min(97, base + bonus)})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:6]


def _build_strengths(top_skills: list[dict[str, Any]], years: int, level: str) -> list[str]:
    bullets = [
        f"Core capability concentrated in {top_skills[0]['skill']} and {top_skills[1]['skill']}.",
        f"{years}+ years experience signal supports a {level.lower()} positioning.",
        "Profile language is action-oriented with good role-to-role continuity.",
    ]
    return bullets


def _build_risk_flags(text_lower: str, missing_keywords: list[str]) -> list[str]:
    flags = []
    if missing_keywords:
        flags.append(f"Missing ATS keywords: {', '.join(missing_keywords[:3])}.")
    if "%" not in text_lower and "increased" not in text_lower and "reduced" not in text_lower:
        flags.append("Limited quantified outcomes; add impact metrics to major achievements.")
    if "summary" not in text_lower and "profile" not in text_lower:
        flags.append("No clear summary statement detected at top of CV.")
    return flags[:3]


def _build_quick_wins(missing_keywords: list[str], text_lower: str) -> list[str]:
    wins = []
    if missing_keywords:
        wins.append(f"Inject missing terms naturally in project bullets: {', '.join(missing_keywords[:3])}.")
    wins.append("Rewrite top 3 bullets with measurable outcomes (%, $, time saved).")
    if "certification" not in text_lower and "certified" not in text_lower:
        wins.append("Add any relevant certifications or notable training in a dedicated section.")
    return wins[:3]


def _build_timeline(level: str, years: int, rng: random.Random) -> list[dict[str, str]]:
    return [
        {"period": f"{max(2016, 2025 - years)}-{max(2018, 2026 - years)}", "role": "Foundation Role", "impact": "Built baseline technical breadth and delivery habits."},
        {"period": f"{max(2018, 2026 - years)}-2023", "role": "Execution Role", "impact": "Expanded ownership and shipped cross-team initiatives."},
        {"period": "2023-Now", "role": f"{level} Role", "impact": f"Driving higher-complexity outcomes and decision quality."},
    ]


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


@bp.get("/legacy-carl")
def carl_legacy_redirect():
    """Placeholder for any old path needing a redirect."""
    return redirect(url_for("carl.carl_dashboard"), code=301)


@bp.get("/carl")
def carl_dashboard():
    """Render Carl CV dashboard demo page."""
    user = session.get("user")
    if not user:
        session["redirect_after_login"] = url_for("carl.carl_dashboard")
        flash("Sign in to use Carl.", "info")
        return redirect(url_for("auth.register"))
    
    uid = user.get("id")
    preloaded = None
    if uid and SUPABASE_URL:
        # Check for eternal persistence
        try:
            from ..models.db import get_db
            db = get_db()
            with db.cursor() as cur:
                cur.execute("SELECT cv_analysis_full FROM profiles WHERE id = %s::uuid", (uid,))
                row = cur.fetchone()
                if row and row[0]:
                    preloaded = row[0]
        except Exception as exc:
            logger.warning("Carl: failed to preload eternal state for %s: %s", uid, exc)

    return render_template("carl.html", wide_layout=True, preloaded_analysis=preloaded)


@bp.post("/carl/analyze")
def carl_analyze():
    """Accept CV upload/text fallback and return deterministic mock analysis."""
    if not session.get("user"):
        return api_error_response("login_required", "Sign in to analyze your CV in Carl.", 401)
    if not csrf_valid():
        return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)

    upload = request.files.get("cv_file")
    has_file = bool(upload and (upload.filename or "").strip())
    text_fallback = (request.form.get("cv_text") or "").strip()
    
    if not has_file and not text_fallback:
        return api_error_response("missing_cv_input", "Upload a PDF/DOCX file or paste CV text.", 400)
    
    if has_file and text_fallback:
        return api_error_response("conflicting_inputs", "Please provide either a file upload OR pasted text, not both.", 400)

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

    user = session.get("user") or {}
    user_id = user.get("id")
    
    cv_url = None
    if user_id and has_file:
        try:
            # Persistent PDF storage
            upload.seek(0)
            file_bytes = upload.read()
            cv_url = upload_cv_to_storage(str(user_id), source.get("filename", "cv.pdf"), file_bytes)
            if cv_url:
                 # Update document source in analysis
                 docs = analysis.get("documents") or []
                 if docs:
                     docs[0]["subtitle"] = f"Vault · {source.get('filename')} · {source.get('byteSize', 0)} bytes"
                     docs[0]["badge"] = "Persistent"
        except Exception as exc:
             logger.warning("Carl persistence upload skipped: %s", exc)

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
                analysis_full=analysis,
                cv_url=cv_url
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
            "developers": url_for("jobs.developers"),
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
        return redirect(url_for("auth.register"))
    mi_tier = _mi_tier(user)
    return render_template(
        report.get("template", "reports/report.html"),
        report=report,
        mi_tier=mi_tier,
        user=user,
    )
