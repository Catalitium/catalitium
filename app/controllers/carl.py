"""Carl CV demo, market research, B2B hiring snapshot, and legacy redirects."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import io
import json
import math
import os
import random
import re
import secrets
import time
from collections import Counter
from statistics import median
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlencode, urlunparse
from urllib.request import Request, urlopen

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from .auth import upload_cv_to_storage
from ..config import (
    CARL4B2B_GUEST_ANALYZE_LIMIT,
    CARL_CHAT_MAX_MESSAGE_CHARS,
    CARL_CHAT_MAX_REPLY_CHARS,
    CARL_CHAT_MAX_TURNS,
    CARL_GUEST_ANALYZE_LIMIT,
)
from ..cv import (
    CVExtractionError,
    extract_cv_from_upload,
    extract_cv_structure,
    normalize_cv_text,
    render_cv,
)
from ..data.catalogs import REPORTS
from ..models.billing import get_user_subscriptions
from ..models.catalog import Job
from ..models.db import (
    SUPABASE_URL,
    _pg_connect,
    fetch_candidate_demand_signal,
    get_db,
    insert_cv_upload_row,
    logger,
    upsert_profile_cv_extract,
    upsert_profile_carl4b2b_analysis,
)
from ..models.money import parse_salary_range_string
from ..utils import (
    COUNTRY_NORM,
    TTLCache,
    api_error_response,
    api_success_response,
    csrf_valid,
    normalize_country,
    normalize_title,
)


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
        _truncate(
            f"[Carl] confidence: heuristic estimate from CV text={narrative_confidence}%",
            _MAX_LINE,
        ),
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
    else:
        logs.append(
            _truncate(
                f"[Carl] matches: none in catalog for persona “{persona}” — use Jobs with your own filters",
                _MAX_LINE,
            )
        )
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

    chat_summary = _build_chat_summary(
        headline=headline,
        persona=persona,
        level=level,
        file_label=file_label,
        matched_keywords=matched_keywords,
        missing_keywords=missing_keywords,
    )
    suggested_prompts = _build_suggested_prompts(missing_keywords, keyword_coverage)

    spotlight_employers: List[Dict[str, Any]] = []

    try:
        from ..models.catalog import Job
        real_jobs = Job.search(persona, None, limit=12, offset=0)
    except Exception:
        real_jobs = []

    recommended_jobs = []
    top_companies = []
    niche_companies = []
    companies_summary: Dict[str, Any] = {
        "sample_rows": 0,
        "rows_with_id": 0,
        "total_matched": 0,
        "match_rate_pct": None,
        "pct_global": None,
        "avg_page_score": None,
        "min_page_score": None,
        "max_page_score": None,
        "median_page_score": None,
        "top_industry": None,
        "spotlight_employer": None,
        "spotlight_page_score": None,
        "spotlight_line": None,
    }

    if real_jobs:
        sample_slice = list(real_jobs[:12])
        enrich_ids = [r.get("id") for r in sample_slice if r.get("id") is not None]
        enrich_map = _fetch_jobs_company_enrichment(enrich_ids)
        companies_summary = _companies_summary_from_rows(sample_slice, enrich_map)
        posting_region = _dominant_posting_region(sample_slice)
        companies_summary["context_ribbon"] = _company_context_ribbon(
            scope_role=persona,
            scope_region=posting_region,
            top_industry=companies_summary.get("top_industry"),
        )
        sm, smore = _spotlight_employers_from_sample(
            sample_slice,
            enrich_map,
            preferred_buckets=_title_bucket_boost(persona),
            market_country_raw=posting_region
            if posting_region != "catalog geography"
            else "",
            limit=3,
        )
        spotlight_employers = sm
        companies_summary["spotlight_more_count"] = smore

        for r in real_jobs[:3]:
            jid = r.get("id")
            job_card: Dict[str, Any] = {
                "title": r.get("job_title", "Unknown Role"),
                "company": r.get("company_name", "Confidential"),
                "location": r.get("location", "Remote"),
                "link": r.get("link", "#"),
            }
            if jid is not None:
                try:
                    job_card["id"] = int(jid)
                except (TypeError, ValueError):
                    job_card["id"] = jid
            _apply_company_enrichment_to_job_card(job_card, enrich_map)
            recommended_jobs.append(job_card)

        if recommended_jobs:
            _pref_b2c = _title_bucket_boost(persona)
            recommended_jobs.sort(key=lambda c: _job_card_rank_key(c, _pref_b2c))

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

        mr_b2c = companies_summary.get("match_rate_pct")
        if mr_b2c is not None and float(mr_b2c) < 12.0:
            risk_flags.append(
                "Low employer directory match in this pulled sample (<12% rows linked via name bridge); "
                "industry and page-score badges reflect partial coverage."
            )
        fit_tail_b2c: List[str] = []
        if companies_summary.get("spotlight_line"):
            fit_tail_b2c.append(str(companies_summary["spotlight_line"]))
        if companies_summary.get("match_rate_pct") is not None:
            fit_tail_b2c.append(
                f"Directory match rate (sample): {companies_summary['match_rate_pct']}% of job rows with id."
            )
        if fit_tail_b2c:
            fit_summary = _truncate(fit_summary + " " + " ".join(fit_tail_b2c), 280)

        if spotlight_employers:
            s0 = spotlight_employers[0]
            nm = s0.get("name")
            if nm:
                ps0 = s0.get("page_score")
                chat_summary = _truncate(
                    chat_summary
                    + " Directory spotlight: "
                    + str(nm)
                    + (f" (page score {ps0})." if ps0 is not None else "."),
                    350,
                )

    if not real_jobs:
        risk_flags = [
            (
                f"No indexed job postings matched inferred role “{persona}” in the catalog. "
                "Use Search jobs with your own title and region."
            ),
            *list(risk_flags),
        ]

    # Terminal logs with match context (no placeholder employers)
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
        },
        "companies_summary": companies_summary,
        "spotlight_employers": spotlight_employers,
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

# =============================================================================
# Guest analyze quotas (session)
# =============================================================================

# Flask session keys — incremented only after a successful POST .../analyze (anonymous only).
CARL_GUEST_ANALYZE_SESSION_KEY = "carl_guest_analyze_count"
CARL4B2B_GUEST_ANALYZE_SESSION_KEY = "carl4b2b_guest_analyze_count"


def guest_analyze_remaining(
    session_obj: Any, *, user: Any, count_key: str, limit: int
) -> Optional[int]:
    """None if logged in (unlimited). Otherwise analyses remaining before next POST."""
    if user:
        return None
    used = int(session_obj.get(count_key) or 0)
    return max(0, limit - used)


def guest_quota_exceeded_response(register_url: str) -> Tuple[Response, int]:
    return api_error_response(
        "signup_required",
        "You've used this session's free previews. Create a free account to keep going and save your work.",
        403,
        details={"register_url": register_url, "remaining": 0},
    )


def enforce_guest_analyze_quota(
    session_obj: Any,
    user: Any,
    *,
    count_key: str,
    limit: int,
    register_url: str,
) -> Optional[Tuple[Response, int]]:
    """If anonymous and quota exhausted, return error response; else None."""
    if user:
        return None
    used = int(session_obj.get(count_key) or 0)
    if used >= limit:
        return guest_quota_exceeded_response(register_url)
    return None


def increment_guest_analyze_if_anonymous(session_obj: Any, user: Any, count_key: str) -> None:
    if user:
        return
    session_obj[count_key] = int(session_obj.get(count_key) or 0) + 1
    session_obj.modified = True


def carl_guest_template_vars(session_obj: Any, user: Any, *, limit: int) -> Dict[str, Any]:
    """Context for Individuals GET /carl."""
    if user:
        return {
            "is_guest": False,
            "carl_guest_remaining": None,
            "carl_guest_limit": None,
        }
    rem = guest_analyze_remaining(
        session_obj, user=user, count_key=CARL_GUEST_ANALYZE_SESSION_KEY, limit=limit
    )
    return {
        "is_guest": True,
        "carl_guest_remaining": rem,
        "carl_guest_limit": limit,
    }


def carl_business_guest_template_vars(session_obj: Any, user: Any, *, limit: int) -> Dict[str, Any]:
    """Context for B2B GET /carl/b2b."""
    if user:
        return {
            "is_guest": False,
            "carl4b2b_guest_remaining": None,
            "carl4b2b_guest_limit": None,
        }
    rem = guest_analyze_remaining(
        session_obj, user=user, count_key=CARL4B2B_GUEST_ANALYZE_SESSION_KEY, limit=limit
    )
    return {
        "is_guest": True,
        "carl4b2b_guest_remaining": rem,
        "carl4b2b_guest_limit": limit,
    }

# =============================================================================
# Brave Search (external context; does not affect scores)
# =============================================================================

BraveContextType = Literal["company", "role_market", "competitor"]

BRAVE_API_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
BRAVE_TIMEOUT_SECONDS = 3
BRAVE_SESSION_LIMIT = 3
BRAVE_RESULT_MAX = 5
BRAVE_SNIPPET_MAX_CHARS = 200
BRAVE_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h
BRAVE_CACHE_MAX_ENTRIES = 500

BRAVE_CACHE = TTLCache(ttl_seconds=BRAVE_CACHE_TTL_SECONDS, max_size=BRAVE_CACHE_MAX_ENTRIES)

_VALID_CONTEXT_TYPES = ("company", "role_market", "competitor")
_WHITESPACE_RE = re.compile(r"\s+")


def _brave_clip(value: str, limit: int) -> str:
    if not value:
        return ""
    s = str(value)
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _normalize_query_token(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "").strip())


def build_brave_query(context_type: str, meta: Dict[str, Any]) -> str:
    """Deterministic query string for a given context type and analysis meta.

    ``meta`` is expected to contain any of: company (str), title (str),
    country (str), top_hirers (list[str]). Missing values are skipped so
    the final query stays short and relevant.
    """
    ctx = (context_type or "").strip().lower()
    if ctx not in _VALID_CONTEXT_TYPES:
        return ""

    year = datetime.now(timezone.utc).year
    company = _normalize_query_token(str(meta.get("company") or ""))
    title = _normalize_query_token(str(meta.get("title") or ""))
    country = _normalize_query_token(str(meta.get("country") or ""))
    top_hirers = meta.get("top_hirers") or []
    if not isinstance(top_hirers, (list, tuple)):
        top_hirers = []
    top_hirers = [
        _normalize_query_token(str(x))
        for x in top_hirers
        if _normalize_query_token(str(x))
    ][:3]

    if ctx == "company":
        if not company:
            return ""
        return f'"{company}" hiring news {year}'

    if ctx == "role_market":
        parts: List[str] = []
        if title:
            parts.append(f'"{title}"')
        parts.append("hiring market")
        if country:
            parts.append(country)
        parts.append(str(year))
        return " ".join(parts).strip()

    if ctx == "competitor":
        if not top_hirers:
            return ""
        quoted = " OR ".join(f'"{h}"' for h in top_hirers)
        return f"{quoted} hiring announcements {year}"

    return ""


def _parse_brave_payload(payload: Any) -> List[Dict[str, str]]:
    """Best-effort normalization of a Brave Search JSON response.

    Returns up to ``BRAVE_RESULT_MAX`` items with string fields truncated.
    Any parsing error for an individual item is silently skipped — we never
    raise from parse.
    """
    if not isinstance(payload, dict):
        return []
    web = payload.get("web") if isinstance(payload.get("web"), dict) else {}
    items = web.get("results") if isinstance(web, dict) else None
    if not isinstance(items, list):
        return []

    out: List[Dict[str, str]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            title = _brave_clip(str(raw.get("title") or ""), BRAVE_SNIPPET_MAX_CHARS)
            url = str(raw.get("url") or "").strip()
            description = _brave_clip(
                str(raw.get("description") or ""),
                BRAVE_SNIPPET_MAX_CHARS,
            )
            age = _brave_clip(str(raw.get("age") or ""), 64)
        except Exception:  # defensive; never raise from parser
            continue
        if not title or not url:
            continue
        if not (url.startswith("https://") or url.startswith("http://")):
            continue
        out.append(
            {
                "title": title,
                "url": url,
                "description": description,
                "age": age,
            }
        )
        if len(out) >= BRAVE_RESULT_MAX:
            break
    return out


def _cache_key(query: str) -> str:
    return "brave:v1:" + _normalize_query_token(query).lower()


def fetch_brave_context(
    query: str,
    *,
    api_key: Optional[str] = None,
    now: Optional[datetime] = None,  # accepted for test injection; unused internally
) -> Optional[List[Dict[str, str]]]:
    """Fetch (or return cached) Brave Search results for ``query``.

    Returns a list of normalized snippet dicts on success, ``None`` on any
    failure (missing key, network error, timeout, non-200 response,
    unparseable body). Callers must treat ``None`` as "external context
    unavailable" and never block the main analysis path on it.
    """
    del now  # reserved for future deterministic-clock tests

    q = _normalize_query_token(query)
    if not q:
        return None

    cache_key = _cache_key(q)
    cached = BRAVE_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)

    key = (api_key or os.getenv("BRAVE_SEARCH_API_KEY") or "").strip()
    if not key:
        return None

    params = {
        "q": q,
        "count": str(BRAVE_RESULT_MAX),
        "safesearch": "moderate",
    }
    url = f"{BRAVE_API_ENDPOINT}?{urlencode(params)}"
    req = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "X-Subscription-Token": key,
            "User-Agent": "catalitium-carl4b2b/1.0",
        },
    )

    start = time.time()
    try:
        with urlopen(req, timeout=BRAVE_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                logger.info("brave: non-200 status=%s q=%r", status, q)
                return None
            raw_body = resp.read()
    except HTTPError as exc:
        logger.info("brave: http_error status=%s q=%r", getattr(exc, "code", "?"), q)
        return None
    except URLError as exc:
        logger.info("brave: url_error reason=%r q=%r", getattr(exc, "reason", "?"), q)
        return None
    except Exception as exc:  # defensive; never raise
        logger.warning("brave: unexpected error type=%s q=%r", type(exc).__name__, q)
        return None

    elapsed_ms = int((time.time() - start) * 1000)
    logger.info("brave: ok elapsed_ms=%s bytes=%s", elapsed_ms, len(raw_body or b""))

    try:
        payload = json.loads(raw_body.decode("utf-8", errors="replace"))
    except Exception:
        return None

    normalized = _parse_brave_payload(payload)
    if not normalized:
        # Cache empty result briefly-ish to avoid pounding Brave on a bad query.
        # Same TTL for simplicity; UI treats empty list as "no external signals".
        BRAVE_CACHE.set(cache_key, [])
        return []

    BRAVE_CACHE.set(cache_key, normalized)
    return list(normalized)


# =============================================================================
# Ghost likelihood score (catalog sample)
# =============================================================================

_MAX_RAW_POINTS = 75

_AGE_BAND_FRESH_ABS = 14
_AGE_BAND_FRESHER_REL = -14
_AGE_BAND_TYPICAL_REL = 14
_AGE_BAND_OLDER_REL = 30

_MIN_ROWS_FOR_MEDIAN = 3

_LABEL_ACTIVE = "Active"
_LABEL_UNCERTAIN = "Uncertain"
_LABEL_LOW = "Low hiring signal"


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[: len(fmt)], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_posting_age_days(value: Any, now: Optional[datetime] = None) -> Optional[int]:
    posted = _to_date(value)
    if posted is None:
        return None
    today = (now or datetime.now(timezone.utc)).date()
    return max(0, (today - posted).days)


def compute_sample_median_age_days(
    rows: Iterable[Mapping[str, Any]],
    now: Optional[datetime] = None,
) -> Optional[int]:
    """Median posting age across parseable rows, or None if too few rows.

    Used to turn the age factor into a sample-relative signal so a
    globally stale or globally fresh catalog does not produce a wall of
    identical scores.
    """
    ages: List[int] = []
    for r in rows:
        age = parse_posting_age_days(r.get("date"), now=now)
        if age is not None:
            ages.append(age)
    if len(ages) < _MIN_ROWS_FOR_MEDIAN:
        return None
    return int(round(median(ages)))


def _repost_key(row: Mapping[str, Any]) -> Tuple[str, str]:
    company = str(row.get("company_name") or "").strip().lower()
    title = str(row.get("job_title_norm") or row.get("job_title") or "").strip().lower()
    return company, title


def compute_repost_index(rows: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str], int]:
    counter: Counter[Tuple[str, str]] = Counter()
    for r in rows:
        key = _repost_key(r)
        if key[0] and key[1]:
            counter[key] += 1
    return dict(counter)


def has_salary_signal(row: Mapping[str, Any]) -> bool:
    raw = row.get("job_salary_range")
    if raw is None:
        return False
    parsed = parse_salary_range_string(str(raw))
    if parsed is None:
        return False
    return 0 < parsed < 2_000_000


def _age_factor(
    age_days: Optional[int],
    sample_median_age_days: Optional[int] = None,
) -> Dict[str, Any]:
    if age_days is None:
        return {
            "key": "age",
            "label": "Posting age unknown",
            "detail": "No usable date on this listing.",
            "points": 10,
        }
    if age_days <= _AGE_BAND_FRESH_ABS:
        return {
            "key": "age",
            "label": f"Fresh ({age_days}d)",
            "detail": "Posted within 2 weeks.",
            "points": 0,
        }
    if sample_median_age_days is None:
        # Too few rows to compute a meaningful sample median; fall back to
        # absolute mild/elevated/stale bands so single-row callers still work.
        if age_days <= 30:
            return {"key": "age", "label": f"Mild ({age_days}d)", "detail": "Between 2 weeks and 1 month old.", "points": 10}
        if age_days <= 60:
            return {"key": "age", "label": f"Elevated ({age_days}d)", "detail": "Between 1 and 2 months old.", "points": 25}
        return {"key": "age", "label": f"Stale ({age_days}d)", "detail": "Older than 2 months.", "points": 40}

    delta = age_days - sample_median_age_days
    median_note = f"median in sample {sample_median_age_days}d"
    if delta <= _AGE_BAND_FRESHER_REL:
        return {
            "key": "age",
            "label": f"Fresher than peers ({age_days}d)",
            "detail": f"More than 2 weeks newer than the {median_note}.",
            "points": 0,
        }
    if delta <= _AGE_BAND_TYPICAL_REL:
        return {
            "key": "age",
            "label": f"Typical for sample ({age_days}d)",
            "detail": f"Within 2 weeks of the {median_note}.",
            "points": 10,
        }
    if delta <= _AGE_BAND_OLDER_REL:
        return {
            "key": "age",
            "label": f"Older than peers ({age_days}d)",
            "detail": f"Two to four weeks older than the {median_note}.",
            "points": 25,
        }
    return {
        "key": "age",
        "label": f"Oldest in sample ({age_days}d)",
        "detail": f"More than a month older than the {median_note}.",
        "points": 40,
    }


def _repost_factor(count: int) -> Dict[str, Any]:
    if count <= 1:
        return {"key": "repost", "label": "Single listing", "detail": "Not seen repeated in this sample.", "points": 0}
    if count == 2:
        return {"key": "repost", "label": "Repost x2", "detail": "Same role at same company appears twice in sample.", "points": 10}
    return {"key": "repost", "label": f"Repost x{count}", "detail": "Same role at same company repeats in sample.", "points": 20}


def _salary_factor(has_salary: bool) -> Dict[str, Any]:
    if has_salary:
        return {"key": "salary", "label": "Salary disclosed", "detail": "Parseable compensation range on the listing.", "points": 0}
    return {"key": "salary", "label": "No salary disclosed", "detail": "Posting does not expose a usable compensation range.", "points": 15}


def _velocity_placeholder_factor() -> Dict[str, Any]:
    return {
        "key": "velocity",
        "label": "Velocity mismatch (scheduled)",
        "detail": "Requires jobs.last_seen_at; not active in this build.",
        "points": 0,
    }


def ghost_label(score: int) -> str:
    if score >= 50:
        return _LABEL_LOW
    if score >= 25:
        return _LABEL_UNCERTAIN
    return _LABEL_ACTIVE


def compute_ghost_score(
    row: Mapping[str, Any],
    repost_index: Mapping[Tuple[str, str], int],
    *,
    sample_median_age_days: Optional[int] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    try:
        age_days = parse_posting_age_days(row.get("date"), now=now)
        repost_count = int(repost_index.get(_repost_key(row), 1))
        factors: List[Dict[str, Any]] = [
            _age_factor(age_days, sample_median_age_days),
            _repost_factor(repost_count),
            _salary_factor(has_salary_signal(row)),
            _velocity_placeholder_factor(),
        ]
        raw = sum(int(f["points"]) for f in factors)
        score = int(round(raw * 100 / _MAX_RAW_POINTS))
        score = max(0, min(100, score))
        return {"score": score, "label": ghost_label(score), "factors": factors}
    except Exception as exc:
        return {
            "score": 50,
            "label": _LABEL_UNCERTAIN,
            "factors": [
                {"key": "error", "label": "Scoring failed", "detail": f"{type(exc).__name__}: {exc}", "points": 0}
            ],
        }

# =============================================================================
# Salary drift (catalog sample)
# =============================================================================

DEFAULT_MIN_SAMPLES = 10

_STABLE_THRESHOLD_PCT = 5.0
_MAX_REASONABLE_ANNUAL = 2_000_000


def _coerce_salary(value: Any) -> Optional[int]:
    if value is None:
        return None
    parsed = parse_salary_range_string(str(value))
    if parsed is None:
        return None
    if not (0 < parsed < _MAX_REASONABLE_ANNUAL):
        return None
    return int(round(parsed))


def _collect_pairs(
    rows: Iterable[Mapping[str, Any]],
    now: Optional[datetime],
) -> List[Tuple[int, int]]:
    pairs: List[Tuple[int, int]] = []
    for r in rows:
        salary = _coerce_salary(r.get("job_salary_range"))
        if salary is None:
            continue
        age = parse_posting_age_days(r.get("date"), now=now)
        if age is None:
            continue
        pairs.append((int(age), salary))
    return pairs


def _direction(delta_pct: float) -> Tuple[str, str]:
    if delta_pct >= _STABLE_THRESHOLD_PCT:
        return "up", "Trending up"
    if delta_pct <= -_STABLE_THRESHOLD_PCT:
        return "down", "Trending down"
    return "flat", "Stable"


def compute_salary_drift(
    rows: Iterable[Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> Dict[str, Any]:
    pairs = _collect_pairs(rows, now=now)
    sample_size = len(pairs)
    if sample_size < min_samples:
        return {
            "status": "insufficient_data",
            "sample_size": sample_size,
            "min_required": int(min_samples),
            "note": (
                f"Need at least {int(min_samples)} listings with parseable salary "
                f"and date; got {sample_size}."
            ),
        }

    # Sort newer-first (ascending age), then split halves. For an odd sample
    # size the middle row is included in the older half (conservative: keeps
    # the "newer" half as strictly newer).
    pairs.sort(key=lambda p: p[0])
    mid = sample_size // 2
    newer = pairs[:mid]
    older = pairs[mid:]

    newer_salaries = [s for _, s in newer]
    older_salaries = [s for _, s in older]
    newer_ages = [a for a, _ in newer]
    older_ages = [a for a, _ in older]

    new_med = int(round(median(newer_salaries)))
    old_med = int(round(median(older_salaries)))
    delta_abs = new_med - old_med
    delta_pct = round((delta_abs / old_med) * 100.0, 1) if old_med > 0 else 0.0

    direction, direction_label = _direction(delta_pct)

    return {
        "status": "ok",
        "sample_size": sample_size,
        "min_required": int(min_samples),
        "direction": direction,
        "direction_label": direction_label,
        "delta_abs": int(delta_abs),
        "delta_pct": delta_pct,
        "newer_half": {
            "count": len(newer),
            "median_salary": new_med,
            "age_min": int(min(newer_ages)) if newer_ages else 0,
            "age_max": int(max(newer_ages)) if newer_ages else 0,
        },
        "older_half": {
            "count": len(older),
            "median_salary": old_med,
            "age_min": int(min(older_ages)) if older_ages else 0,
            "age_max": int(max(older_ages)) if older_ages else 0,
        },
        "note": (
            f"Based on {sample_size} listings with parseable salary. "
            "Directional over catalog sample, not a forecast."
        ),
    }

carl_business_bp = Blueprint("carl_business", __name__, url_prefix="/carl/b2b")

_MAX_LINE = 140
_SAMPLE_CAP = 400

# Default catalog title family when the user only supplies a company URL (bounded search).
_DEFAULT_TITLE_FAMILY = "software"

# Consolidated industry buckets aligned with ``public.get_industry_bucket`` (``jobs_with_company`` view).
CARL_MARKET_INDUSTRY_BUCKETS: Tuple[str, ...] = (
    "Tech",
    "Finance",
    "Healthcare",
    "Retail",
    "Manufacturing",
    "Media",
    "Education",
    "Legal",
    "Consulting",
    "Energy",
    "Government",
    "Other",
)

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


def _host_variants_for_company_lookup(hostname: str) -> List[str]:
    """Ordered host keys to match ``companies.website`` (subdomain then registrable-ish parent)."""
    h = (hostname or "").lower().strip()
    if not h:
        return []
    if "@" in h:
        h = h.split("@")[-1]
    if h.startswith("www."):
        h = h[4:]
    out: List[str] = []
    seen: set[str] = set()

    def push(x: str) -> None:
        x = x.strip().lower()
        if x and x not in seen:
            seen.add(x)
            out.append(x)

    push(h)
    parts = h.split(".")
    if len(parts) >= 3:
        push(".".join(parts[1:]))
    return out


def lookup_company_directory_hints(canonical_url: str) -> Dict[str, Optional[str]]:
    """Match ``companies.website`` host to enrich URL-only runs (industry, region, display name).

    Safe no-op when the table is missing or DB is unavailable.
    """
    blank: Dict[str, Optional[str]] = {"industry": None, "region": None, "comp_name": None}
    if not (canonical_url or "").strip():
        return blank
    try:
        parsed = urlparse(canonical_url)
        host = (parsed.netloc or "").strip()
        variants = _host_variants_for_company_lookup(host)
        if not variants:
            return blank
        db = get_db()
        sql = """
            SELECT industry, region, comp_name
            FROM companies
            WHERE website IS NOT NULL AND btrim(website) <> ''
              AND lower(
                regexp_replace(
                  split_part(
                    regexp_replace(trim(website), '^https?://', '', 'i'),
                    '/',
                    1
                  ),
                  '^www\\.', ''
                )
              ) = %s
            LIMIT 1
            """
        with db.cursor() as cur:
            for v in variants:
                cur.execute(sql, (v,))
                row = cur.fetchone()
                if not row:
                    continue
                ind, reg, name = row[0], row[1], row[2]
                out = {
                    "industry": str(ind).strip() if ind and str(ind).strip() else None,
                    "region": str(reg).strip() if reg and str(reg).strip() else None,
                    "comp_name": str(name).strip() if name and str(name).strip() else None,
                }
                if any(out.values()):
                    return out
    except Exception as exc:
        logger.info("Carl4B2B: company directory lookup skipped: %s", exc)
    return blank


def fetch_distinct_company_industries_for_carl(*, limit: int = 2000) -> List[str]:
    """Short bucket list for Carl comboboxes (not raw ``companies.industry`` noise)."""
    buckets = list(CARL_MARKET_INDUSTRY_BUCKETS)
    if limit and limit < len(buckets):
        return buckets[:limit]
    return buckets


def _b2b_kw_join(words: Sequence[str], limit: int, empty: str = "none") -> str:
    if not words:
        return empty
    return ", ".join([str(w) for w in words[:limit] if str(w).strip()])


def _carl_sql_conn():
    """Return ``(connection, should_close)`` for one-off reads outside Flask ``g.db``."""
    try:
        from flask import has_app_context

        if has_app_context():
            return get_db(), False
    except Exception:
        pass
    if not SUPABASE_URL:
        return None, False
    try:
        return _pg_connect(), True
    except Exception as exc:
        logger.info("carl SQL connection unavailable: %s", exc)
        return None, False


def _numeric_page_score(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and math.isnan(raw):
            return None
        return float(raw)
    s = str(raw).strip().upper()
    if not s or s in ("NA", "N/A", "NULL", "-", "NONE"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _numeric_headcount(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        if math.isnan(raw):
            return None
        return int(raw)
    s = str(raw).strip().upper()
    if not s or s in ("NA", "N/A", "NULL", "-", "NONE"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _headcount_band(n: Optional[int]) -> Optional[str]:
    if n is None or n < 1:
        return None
    if n <= 50:
        return "1–50"
    if n <= 500:
        return "51–500"
    return "500+"


def _market_region_aligns(company_region: str, market_country_raw: str) -> bool:
    reg = (company_region or "").strip().lower()
    if not reg:
        return False
    mc = normalize_country(market_country_raw or "").strip().lower()
    if not mc:
        return False
    return mc in reg or reg in mc


def _dominant_posting_region(rows: Sequence[Mapping[str, Any]]) -> str:
    vals: List[str] = []
    for r in rows:
        c = (r.get("country") or r.get("location") or "").strip()
        if c:
            vals.append(c)
    if not vals:
        return "catalog geography"
    return Counter(vals).most_common(1)[0][0]


def _company_context_ribbon(
    *,
    scope_role: str,
    scope_region: str,
    top_industry: Optional[str],
) -> str:
    ti = top_industry or "—"
    sr = (scope_role or "").strip() or "This focus"
    reg = (scope_region or "").strip() or "This market"
    line = f"{reg} · {sr} · {ti} leads this sample."
    return _truncate(line, 158)


def _spotlight_employers_from_sample(
    rows: Sequence[Mapping[str, Any]],
    enrichment_by_id: Dict[int, Dict[str, Any]],
    *,
    preferred_buckets: set[str],
    market_country_raw: str,
    limit: int = 3,
) -> Tuple[List[Dict[str, Any]], int]:
    dedupe: Dict[str, Tuple[Tuple[int, int, float, float, int], Dict[str, Any]]] = {}
    for r in rows:
        raw_id = r.get("id")
        if raw_id is None:
            continue
        try:
            jid = int(raw_id)
        except (TypeError, ValueError):
            continue
        e = enrichment_by_id.get(jid)
        if not e or e.get("comp_id") is None:
            continue
        name = (r.get("company_name") or "").strip()
        if not name:
            continue
        key = name.casefold()
        ps = e.get("page_score")
        try:
            ps_v = float(ps) if ps is not None else -1.0
        except (TypeError, ValueError):
            ps_v = -1.0
        hc_n = _numeric_headcount(e.get("company_headcount"))
        hc_sort = float(hc_n) if hc_n is not None else -1.0
        reg = str(e.get("company_region") or "").strip()
        ib = e.get("industry_bucket")
        ib_s = str(ib) if ib else ""
        bucket_align = 1 if (ib_s and ib_s in preferred_buckets) else 0
        region_align = 1 if _market_region_aligns(reg, market_country_raw) else 0
        sort_tuple = (region_align, bucket_align, ps_v, hc_sort, jid)
        card: Dict[str, Any] = {
            "name": name,
            "page_score": round(ps_v, 2) if ps_v >= 0 else None,
            "headcount_band": _headcount_band(hc_n),
            "company_region": reg or None,
            "industry_bucket": ib_s or None,
            "link": str(r.get("link") or "#"),
        }
        prev = dedupe.get(key)
        if prev is None or sort_tuple > prev[0]:
            dedupe[key] = (sort_tuple, card)
    ordered = [t[1] for t in sorted(dedupe.values(), key=lambda x: x[0], reverse=True)]
    more = max(0, len(ordered) - limit)
    return ordered[:limit], more


def _fetch_jobs_company_enrichment(job_ids: Sequence[Any]) -> Dict[int, Dict[str, Any]]:
    """Lookup ``jobs_with_company`` rows by job id; empty dict on missing DB/view."""
    ids: List[int] = []
    for raw in job_ids:
        if raw is None:
            continue
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}
    conn, own = _carl_sql_conn()
    if conn is None:
        return {}
    out: Dict[int, Dict[str, Any]] = {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, comp_id, industry_bucket, is_global, page_score,
                       company_region, company_headcount
                FROM jobs_with_company
                WHERE id = ANY(%s)
                """,
                (ids,),
            )
            for row in cur.fetchall() or ():
                (
                    jid,
                    comp_id,
                    industry_bucket,
                    is_global,
                    page_score,
                    company_region,
                    company_headcount,
                ) = row
                ig: Optional[bool]
                if is_global is None:
                    ig = None
                else:
                    ig = bool(is_global)
                cr = (str(company_region).strip() if company_region is not None else "") or None
                out[int(jid)] = {
                    "comp_id": comp_id,
                    "industry_bucket": industry_bucket,
                    "is_global": ig,
                    "page_score": _numeric_page_score(page_score),
                    "company_region": cr,
                    "company_headcount": _numeric_headcount(company_headcount),
                }
    except Exception as exc:
        logger.info("jobs_with_company enrich skipped: %s", exc)
        return {}
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass
    return out


def _title_bucket_boost(title_raw: str) -> set[str]:
    """Soft relevance: title keywords imply preferred ``industry_bucket`` labels (12-bucket fn)."""
    t = (title_raw or "").lower()
    s: set[str] = set()
    if any(x in t for x in ("data", "scientist", "analyst", "machine learning", "ml ", " bi ")):
        s.update({"Tech", "Finance", "Healthcare", "Consulting"})
    if any(x in t for x in ("engineer", "developer", "software", "devops", "sre", "platform", "backend", "frontend")):
        s.update({"Tech", "Manufacturing"})
    if any(x in t for x in ("product", "manager", "pm ", "program manager")):
        s.update({"Tech", "Media", "Retail", "Finance"})
    if any(x in t for x in ("finance", "accounting", "risk", "bank", "trading")):
        s.add("Finance")
    if any(x in t for x in ("marketing", "growth", "content", "brand")):
        s.update({"Media", "Retail"})
    if any(x in t for x in ("nurse", "clinical", "health", "pharma", "biotech", "medical")):
        s.add("Healthcare")
    if not s:
        s.add("Tech")
    return s


def _demand_bucket_from_title_query(title_blob: str) -> str:
    """Pick a single ``CARL_MARKET_INDUSTRY_BUCKETS`` label (for demand rollups + cv_uploads)."""
    s = _title_bucket_boost(title_blob or "")
    for b in CARL_MARKET_INDUSTRY_BUCKETS:
        if b in s:
            return b
    return "Other"


def _infer_carl_industry_bucket(headline: str, persona: str, skills: Sequence[str]) -> str:
    blob = " ".join([headline or "", persona or "", " ".join([str(x) for x in (skills or []) if x])])
    return _demand_bucket_from_title_query(blob)


def _infer_country_from_cv_text(cv_text: str) -> Optional[str]:
    """Best-effort ISO-ish code from CV text (aligned with ``normalize_country``)."""
    tl = (cv_text or "").lower()
    try:
        for token in sorted(COUNTRY_NORM.keys(), key=len, reverse=True):
            if len(token) < 2:
                continue
            if re.search(rf"\b{re.escape(str(token))}\b", tl):
                code = normalize_country(str(token))
                if code:
                    return code
    except Exception:
        pass
    return None


def _job_card_rank_key(card: Mapping[str, Any], preferred_buckets: set[str]) -> Tuple[int, int, float, int]:
    bucket = card.get("industry_bucket")
    align = 1 if (bucket and bucket in preferred_buckets) else 0
    matched = 1 if card.get("directory_match") else 0
    ps = card.get("page_score")
    try:
        ps_v = float(ps) if ps is not None else -1.0
    except (TypeError, ValueError):
        ps_v = -1.0
    jid = card.get("id")
    try:
        id_v = int(jid) if jid is not None else 0
    except (TypeError, ValueError):
        id_v = 0
    return (-align, -matched, -ps_v, id_v)


def _companies_summary_from_rows(
    rows: Sequence[Mapping[str, Any]],
    enrichment_by_id: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    sample_rows = len(rows)
    matched = 0
    rows_with_id = 0
    global_n = 0
    scores: List[float] = []
    industries: List[str] = []
    spotlight_name: Optional[str] = None
    spotlight_score: Optional[float] = None
    for r in rows:
        raw_id = r.get("id")
        if raw_id is None:
            continue
        try:
            jid = int(raw_id)
        except (TypeError, ValueError):
            continue
        rows_with_id += 1
        e = enrichment_by_id.get(jid)
        if not e or e.get("comp_id") is None:
            continue
        matched += 1
        if e.get("is_global") is True:
            global_n += 1
        ps = e.get("page_score")
        if ps is not None:
            fv = float(ps)
            scores.append(fv)
            cname = (r.get("company_name") or "").strip()
            if cname and (spotlight_score is None or fv > spotlight_score):
                spotlight_score = fv
                spotlight_name = cname
        ib = e.get("industry_bucket")
        if ib:
            industries.append(str(ib))
    top = Counter(industries).most_common(1)
    match_rate_pct = (
        round(100 * matched / rows_with_id, 1) if rows_with_id else None
    )
    med = median(scores) if scores else None
    spotlight_line: Optional[str] = None
    if spotlight_name and spotlight_score is not None:
        spotlight_line = (
            f"Strongest directory signal in sample: {spotlight_name} "
            f"(page score {round(float(spotlight_score), 2)})."
        )
    return {
        "sample_rows": sample_rows,
        "rows_with_id": rows_with_id,
        "total_matched": matched,
        "match_rate_pct": match_rate_pct,
        "pct_global": round(100 * global_n / matched, 1) if matched else None,
        "avg_page_score": round(sum(scores) / len(scores), 2) if scores else None,
        "min_page_score": round(min(scores), 2) if scores else None,
        "max_page_score": round(max(scores), 2) if scores else None,
        "median_page_score": round(float(med), 2) if med is not None else None,
        "top_industry": top[0][0] if top else None,
        "spotlight_employer": spotlight_name,
        "spotlight_page_score": round(float(spotlight_score), 2) if spotlight_score is not None else None,
        "spotlight_line": spotlight_line,
    }


def _apply_company_enrichment_to_job_card(
    card: Dict[str, Any],
    enrichment_by_id: Dict[int, Dict[str, Any]],
) -> None:
    raw_id = card.get("id")
    if raw_id is None:
        return
    try:
        jid = int(raw_id)
    except (TypeError, ValueError):
        return
    e = enrichment_by_id.get(jid)
    if not e or e.get("comp_id") is None:
        return
    card["directory_match"] = True
    if e.get("is_global") is True:
        card["is_global"] = True
    ib = e.get("industry_bucket")
    card["industry_bucket"] = str(ib) if ib else None
    ps = e.get("page_score")
    if ps is not None:
        card["page_score"] = round(float(ps), 2)
    reg = e.get("company_region")
    if reg:
        card["company_region"] = str(reg).strip()[:120] or None
    hb = _headcount_band(e.get("company_headcount"))
    if hb:
        card["headcount_band"] = hb


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

    def _intensity_tier(c: int) -> tuple[str, str]:
        if c >= 5:
            return ("high", "High")
        if c >= 2:
            return ("medium", "Medium")
        return ("low", "Low")

    top_companies = []
    for n, c_raw in top_pairs[:8]:
        c = int(c_raw)
        tier_key, tier_label = _intensity_tier(c)
        top_companies.append(
            {
                "name": n,
                "post_count": c,
                "intensity_tier": tier_key,
                "intensity_label": tier_label,
                "reason": f"{c} postings in catalog sample · indexed titles only",
            }
        )
    niche_pool = [(n, c) for n, c in top_pairs if c == 1][:6]
    niche_companies = [
        {"name": n, "reason": "Low-volume hirer in this sample; treat as directional."}
        for n, _ in niche_pool
    ]

    now_utc = datetime.now(timezone.utc)
    repost_index = compute_repost_index(rows)
    sample_median_age = compute_sample_median_age_days(rows, now=now_utc)
    salary_drift = compute_salary_drift(rows, now=now_utc)

    eligible_rows = [
        r
        for r in rows
        if not (exclude and exclude in str(r.get("company_name") or "").lower())
    ]
    elig_ids = [r.get("id") for r in eligible_rows if r.get("id") is not None]
    enrichment_by_id = _fetch_jobs_company_enrichment(elig_ids)
    companies_summary = _companies_summary_from_rows(eligible_rows, enrichment_by_id)
    companies_summary["context_ribbon"] = _company_context_ribbon(
        scope_role=title_q or "open titles",
        scope_region=country_q or "catalog geography",
        top_industry=companies_summary.get("top_industry"),
    )
    spotlight_employers, spotlight_more = _spotlight_employers_from_sample(
        eligible_rows,
        enrichment_by_id,
        preferred_buckets=_title_bucket_boost(title_q),
        market_country_raw=country_q,
        limit=3,
    )
    companies_summary["spotlight_more_count"] = spotlight_more

    job_cards: List[Dict[str, Any]] = []
    for r in rows[:8]:
        if exclude and exclude in str(r.get("company_name") or "").lower():
            continue
        jid = r.get("id")
        card: Dict[str, Any] = {
            "title": str(r.get("job_title") or "Role"),
            "company": str(r.get("company_name") or "—"),
            "location": str(r.get("location") or r.get("city") or r.get("country") or "—"),
            "link": str(r.get("link") or "/jobs"),
            "ghost": compute_ghost_score(
                r,
                repost_index,
                sample_median_age_days=sample_median_age,
                now=now_utc,
            ),
        }
        if jid is not None:
            try:
                card["id"] = int(jid)
            except (TypeError, ValueError):
                card["id"] = jid
        _apply_company_enrichment_to_job_card(card, enrichment_by_id)
        job_cards.append(card)

    _pref_b2b = _title_bucket_boost(title_q)
    job_cards.sort(key=lambda c: _job_card_rank_key(c, _pref_b2b))

    skills_radar = [
        {
            "skill": n,
            "post_count": int(c),
            "intensity_label": _intensity_tier(int(c))[1],
            "score": int(min(100, 15 + int(c) * 6)),
        }
        for n, c in top_pairs[:10]
    ]

    sum_roll = int(sum(comp_counts.values())) or 1
    top3_c = sum(int(c) for _, c in top_pairs[:3])
    top3_pct = int(min(100, round(100 * top3_c / sum_roll)))
    top1_pct = (
        int(min(100, round(100 * int(top_pairs[0][1]) / sum_roll))) if top_pairs else 0
    )
    median_age_int = sample_median_age
    if median_age_int is None:
        fresh_score = 42
        velocity_human = "Median listing age unavailable for enough rows in this sample."
    else:
        fresh_score = int(max(0, min(100, 100 - min(median_age_int, 75))))
        velocity_human = (
            f"Median posting age ~{median_age_int}d in this pulled sample "
            f"(lower usually means fresher listings for {country_q or 'this region'})."
        )
    sample_coverage_pct = int(min(100, round(100 * sample_n / max(1, total_catalog))))

    scope_industry = title_q or "—"
    scope_region = country_q or "—"
    scope_pair = f"{scope_industry} · {scope_region}"

    b2b_panel: Dict[str, Any] = {
        "scope_industry": scope_industry,
        "scope_region": scope_region,
        "scope_line": scope_pair,
        "kpi_catalog_total": total_catalog,
        "kpi_sample_rows": sample_n,
        "kpi_sample_cap": _SAMPLE_CAP,
        "kpi_distinct_employers": distinct,
        "kpi_top3_share_pct": top3_pct,
        "kpi_top1_share_pct": top1_pct,
        "kpi_median_listing_age_days": median_age_int,
        "kpi_freshness_score": fresh_score,
        "kpi_market_size_line": (
            f"{total_catalog} postings in catalog for {scope_pair}. "
            f"Pulled {sample_n}/{_SAMPLE_CAP} rows · {distinct} employers in sample."
        ),
        "kpi_concentration_line": (
            f"Top 3 hirers hold ~{top3_pct}% of sample rows; largest single hirer ~{top1_pct}%."
        ),
        "kpi_velocity_line": velocity_human,
        "next_actions": [
            f"Prioritize outreach to the top 3 hirers for {scope_pair} — they dominate this slice.",
            "Merge duplicate employer strings (Ltd/Inc/subsidiaries) before sharing internally.",
            "Spot-check live postings for title wording drift vs your reqs for this region.",
        ],
    }

    salary_drift = {**salary_drift, "scope_context": scope_pair}

    mc = (meta.get("market_company") or "").strip()
    if mc and (title_q or country_q):
        headline = f"{mc} — “{title_q or 'open titles'}” in {country_q or 'catalog geography'}"
    else:
        headline = (
            f"Hiring intensity: “{title_q or 'open titles'}” in {country_q or 'catalog geography'}"
        )
    persona = "Indexed job market"
    level = f"{total_catalog} postings (catalog) · sample {sample_n} rows"
    strengths = [
        f"[{scope_pair}] Top hirer in sample: {top_names[0]}" if top_names else f"[{scope_pair}] Sparse matches.",
        f"[{scope_pair}] {distinct} employers in pulled sample ({sample_n} rows).",
    ]
    risk_flags = [
        f"[{scope_pair}] Indexed listings only — not every real vacancy appears here.",
        f"[{scope_pair}] Sample capped at {_SAMPLE_CAP} rows; thin tails disappear first.",
        f"[{scope_pair}] Employer labels are raw strings; consolidate variants before reporting.",
    ]
    if exclude:
        risk_flags.insert(
            0,
            f"Employers whose names contain “{exclude_company.strip()}” are omitted from hirer rollups and sample job cards.",
        )
    if distinct < 8:
        risk_flags.append(
            f"[{scope_pair}] Few distinct employers in sample — widen industry tokens or relax geography.",
        )
    if salary_drift.get("status") == "insufficient_data":
        risk_flags.append(
            f"[{scope_pair}] Insufficient salary+dated rows in sample for pay drift (see salary card).",
        )
    mr = companies_summary.get("match_rate_pct")
    if mr is not None and mr < 12.0:
        risk_flags.append(
            f"[{scope_pair}] Only ~{mr}% of sample job rows linked to the companies directory "
            "(trimmed name match); treat employer chips as partial coverage."
        )

    fit_extra_parts: List[str] = []
    sln = companies_summary.get("spotlight_line")
    if sln:
        fit_extra_parts.append(str(sln))
    if companies_summary.get("match_rate_pct") is not None:
        fit_extra_parts.append(
            f"Directory match rate (sample): {companies_summary['match_rate_pct']}% of rows with job id."
        )
    fit_tail = (" " + " ".join(fit_extra_parts)) if fit_extra_parts else ""

    overview: Dict[str, Any] = {
        "headline": headline,
        "persona": persona,
        "level": level,
        "fitSummary": _truncate(
            f"{headline} "
            f"{total_catalog} catalog postings · {sample_n}/{_SAMPLE_CAP} sample rows · {distinct} employers · "
            f"top-3 share ~{top3_pct}% · median listing age "
            f"{(str(median_age_int) + 'd') if median_age_int is not None else 'n/a'}."
            f"{fit_tail}",
            350,
        ),
        "confidence": sample_coverage_pct,
        "wordCount": sample_n,
        "signalScores": {
            "structure": diversity_pct,
            "keywords": top3_pct,
            "impact": fresh_score,
            "narrative": sample_coverage_pct,
        },
        "premiumSignals": {
            "leadership": top1_pct,
            "roleMatch": top3_pct,
            "evidenceDensity": distinct,
        },
    }

    quick_wins = [
        f"Short-list the top 3 hirers for {scope_pair}; they represent ~{top3_pct}% of this sample.",
        f"If median age is high for {scope_region}, refresh key reqs or widen {scope_industry} tokens.",
        f"Export JSON / copy summary and validate two employer names manually before exec readouts.",
    ]

    matched_kw = top_names[:6] if top_names else ["—"]
    missing_kw: List[str] = []
    if distinct < 5:
        missing_kw.append("more_posting_volume")

    top_h = top_names[0] if top_names else "n/a"
    chat_parts = [
        f"{title_q or '·'} / {country_q or '·'} — {total_catalog} postings, "
        f"{distinct} employer strings in the {_SAMPLE_CAP}-row sample. Top by volume: {top_h}."
    ]
    if companies_summary.get("spotlight_line"):
        chat_parts.append(str(companies_summary["spotlight_line"]))
    if spotlight_employers:
        s0 = spotlight_employers[0]
        nm = s0.get("name")
        if nm:
            ps0 = s0.get("page_score")
            chat_parts.append(
                f"Directory spotlight: {nm}"
                + (f" (page score {ps0})." if ps0 is not None else ".")
            )
    chat_summary = _truncate(" ".join(chat_parts), 350)
    suggested_prompts = [
        f"Which hirers should we prioritize first for {scope_pair} given concentration?",
        f"How fresh are postings for {scope_pair} — should we widen or tighten title tokens?",
        f"What employer name variants in {scope_region} might be splitting volume?",
    ]

    terminal_logs = [
        _truncate(f"[Carl4B2B] audit: catalog_total_postings={total_catalog}", _MAX_LINE),
        _truncate(
            f"[Carl4B2B] audit: sample_rows={sample_n} sample_cap={_SAMPLE_CAP}",
            _MAX_LINE,
        ),
        _truncate(f"[Carl4B2B] audit: distinct_employers_in_sample={distinct}", _MAX_LINE),
        _truncate("[Carl4B2B] catalog: resolving title/country filters", _MAX_LINE),
        _truncate(f"[Carl4B2B] rollup: top employer tokens — {_b2b_kw_join(top_names, 5)}", _MAX_LINE),
        _truncate(
            f"[Carl4B2B] meta: company={meta.get('market_company') or '—'} "
            f"exclude={exclude or '—'} url={meta.get('business_url') or '—'}",
            _MAX_LINE,
        ),
        "[Carl4B2B] synthesis: dashboard payload assembled",
    ]

    market_meta: Dict[str, Any] = {
        "title_q": title_q,
        "country_q": country_q,
        "exclude_company": exclude_company.strip(),
        "market_company": (meta.get("market_company") or "").strip(),
        "sample_rows": sample_n,
        "sample_cap": _SAMPLE_CAP,
        "total_count": total_catalog,
        "distinct_employers_sample": distinct,
        "business_url": (meta.get("business_url") or "").strip(),
        "company_email": (meta.get("company_email") or "").strip(),
        "inferred_from_url": bool(meta.get("inferred_from_url")),
        "inferred_title_family": (meta.get("inferred_title_family") or "").strip(),
        "input_type": str(meta.get("input_type") or "").strip(),
        "directory_match": meta.get("directory_match"),
    }
    demand_sig = fetch_candidate_demand_signal(
        _demand_bucket_from_title_query(title_q),
        country_q,
    )
    if demand_sig:
        market_meta["demandSignal"] = demand_sig

    analysis: Dict[str, Any] = {
        "overview": overview,
        "documents": [
            {
                "title": "Market query",
                "subtitle": f"{(meta.get('market_company') or '').strip() or '—'} · {title_q or '—'} · {country_q or '—'}",
                "badge": "Catalog",
            }
        ],
        "actionFeed": [
            {
                "title": f"Outreach pack — {scope_pair}",
                "subtitle": "Start with the top 3 hirers in this pulled sample.",
                "detail": b2b_panel["next_actions"][0],
            },
            {
                "title": "Normalize employer labels",
                "subtitle": "Subsidiaries and legal suffixes split volume across strings.",
                "detail": b2b_panel["next_actions"][1],
            },
        ],
        "skillsRadar": skills_radar,
        "strengths": strengths,
        "experienceTimeline": [
            {
                "period": scope_pair,
                "role": "Posting concentration (sample)",
                "impact": f"{_b2b_kw_join([f'{n} ({c})' for n, c in top_pairs[:3]], 3, 'n/a')}",
            }
        ],
        "atsScore": {
            "score": saturation,
            "keywordCoverage": diversity_pct,
            "matchedKeywords": matched_kw,
            "missingKeywords": missing_kw,
        },
        "salaryDrift": salary_drift,
        "b2bPanel": b2b_panel,
        "companies_summary": companies_summary,
        "spotlight_employers": spotlight_employers,
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
        "marketMeta": market_meta,
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


def carl_business_effective_user_message(
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
    spotlight = analysis.get("spotlight_employers") or []
    directory_spotlight = ""
    if spotlight and isinstance(spotlight[0], dict):
        n0 = spotlight[0].get("name")
        if n0:
            ps0 = spotlight[0].get("page_score")
            directory_spotlight = (
                f"Directory spotlight: {n0}"
                + (f" (page score {ps0})." if ps0 is not None else ".")
            )
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
        "directorySpotlight": directory_spotlight,
    }


@carl_business_bp.get("")
def carl_business_dashboard():
    user = session.get("user")
    uid = user.get("id") if user else None
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
        "carl/carl_business.html",
        wide_layout=True,
        preloaded_carl4b2b_analysis=preloaded,
        carl_company_industries=fetch_distinct_company_industries_for_carl(),
        **carl_business_guest_template_vars(session, user, limit=CARL4B2B_GUEST_ANALYZE_LIMIT),
    )


@carl_business_bp.get("/url-hints")
def carl_business_url_hints():
    """JSON hints from ``companies`` for a pasted URL (guests allowed; read-only)."""
    raw = str(request.args.get("url") or "").strip()
    if not raw:
        return api_success_response({"hints": None})
    canonical, _, _, _, err = parse_company_url_for_market_map(raw)
    if err or not canonical:
        return api_success_response({"hints": None})
    hints = lookup_company_directory_hints(canonical)
    if not any((hints.get("industry"), hints.get("region"), hints.get("comp_name"))):
        return api_success_response({"hints": None})
    return api_success_response({"hints": hints})


@carl_business_bp.post("/analyze")
def carl_business_analyze():
    if not csrf_valid():
        return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)

    user_raw = session.get("user")
    quota_err = enforce_guest_analyze_quota(
        session,
        user_raw,
        count_key=CARL4B2B_GUEST_ANALYZE_SESSION_KEY,
        limit=CARL4B2B_GUEST_ANALYZE_LIMIT,
        register_url=url_for("auth.register"),
    )
    if quota_err:
        return quota_err

    payload = request.get_json(silent=True) or {}
    business_url_in = str(payload.get("business_url") or "").strip()
    title_in = str(payload.get("title") or payload.get("role_title") or "").strip()
    country_in = str(payload.get("country") or payload.get("location") or "").strip()
    market_company_in = str(payload.get("market_company") or "").strip()
    exclude_in = str(payload.get("exclude_company") or "").strip()

    structured_ok = bool(title_in)
    had_url_input = bool(business_url_in)

    if not structured_ok and not had_url_input:
        return api_error_response(
            "invalid_input",
            "Enter a URL or choose an industry to continue.",
            400,
        )

    canonical_url: Optional[str] = None
    url_title: Optional[str] = None
    url_country: Optional[str] = None
    url_exclude: Optional[str] = None
    url_parse_ignored = False
    if had_url_input:
        canonical_url, url_title, url_country, url_exclude, url_err = parse_company_url_for_market_map(
            business_url_in
        )
        if url_err:
            if structured_ok:
                url_parse_ignored = True
                canonical_url = None
                url_title = None
                url_country = None
                url_exclude = None
            else:
                return api_error_response(
                    "invalid_company_url",
                    "Enter a valid http(s) URL with a hostname (e.g. https://yourcompany.com).",
                    400,
                )

    has_valid_url = bool(canonical_url)

    if not market_company_in:
        if title_in:
            market_company_in = title_in[:64]
        elif canonical_url:
            try:
                chost = (urlparse(canonical_url).hostname or "").lower()
                if chost.startswith("www."):
                    chost = chost[4:]
                market_company_in = (chost or "Market")[:64]
            except Exception:
                market_company_in = "Market"
        else:
            market_company_in = "Market"

    dir_hints = lookup_company_directory_hints(canonical_url or "") if has_valid_url else {}
    directory_match: Optional[Dict[str, str]] = None
    if dir_hints and any(dir_hints.values()):
        directory_match = {
            k: str(v)
            for k, v in dir_hints.items()
            if v and str(v).strip()
        }
        if not directory_match:
            directory_match = None

    db_industry = (dir_hints.get("industry") or "").strip() or None
    db_region = (dir_hints.get("region") or "").strip() or None

    if structured_ok:
        title_raw = title_in
        country_raw = country_in or "Global"
        if exclude_in:
            exclude_company = exclude_in
        elif url_exclude:
            exclude_company = url_exclude
        else:
            exclude_company = ""
        inferred_from_url = False
        inferred_title_family = title_in
        input_type = "manual"
        if has_valid_url:
            input_type = "mixed"
    else:
        title_raw = title_in or db_industry or url_title or ""
        country_raw = (country_in or db_region or url_country or "").strip() or "Global"
        exclude_company = url_exclude or ""
        inferred_from_url = not bool(title_in or country_in)
        inferred_title_family = _DEFAULT_TITLE_FAMILY if inferred_from_url else (title_in or _DEFAULT_TITLE_FAMILY)
        input_type = "company_url"

    company_email = str(payload.get("company_email") or "").strip()

    meta = {
        "business_url": (canonical_url or ""),
        "company_email": company_email,
        "market_company": market_company_in,
        "inferred_from_url": inferred_from_url,
        "inferred_title_family": inferred_title_family,
        "input_type": input_type,
        "directory_match": directory_match,
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
            "invalid_input",
            "Could not build a catalog query from those filters. Try a clearer role title and country.",
            400,
        )

    if structured_ok:
        pre_logs = [
            _truncate(
                f"[Carl4B2B] input={input_type} title≈{title_q} country≈{country_q or '—'} "
                f"exclude≈{(exclude_company or '—').lower()}",
                _MAX_LINE,
            ),
        ]
        if canonical_url:
            pre_logs.append(_truncate(f"[Carl4B2B] company_url: {canonical_url}", _MAX_LINE))
        if url_parse_ignored:
            pre_logs.append(
                "[Carl4B2B] note: careers URL was invalid and ignored; using role + country only."
            )
    else:
        pre_logs = [
            _truncate(f"[Carl4B2B] company_url: {canonical_url}", _MAX_LINE),
            _truncate(
                f"[Carl4B2B] inferred: title≈{title_q} country≈{country_q or '—'} exclude≈{(exclude_company or '—').lower()}",
                _MAX_LINE,
            ),
        ]
    if directory_match:
        pre_logs.append(
            _truncate(
                "[Carl4B2B] directory: "
                + str(directory_match.get("comp_name") or "—")
                + " · industry≈"
                + str(directory_match.get("industry") or "—")
                + " region≈"
                + str(directory_match.get("region") or "—"),
                _MAX_LINE,
            )
        )
    analysis["terminalLogs"] = pre_logs + list(analysis.get("terminalLogs") or [])

    user = user_raw or {}
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
    session["carl4b2b_brave_count"] = 0
    session["carl4b2b_brave_meta"] = _build_brave_session_meta(
        analysis=analysis,
        canonical_url=canonical_url,
        title_q=title_q,
        country_q=country_q,
    )
    session.modified = True

    source = {
        "inputType": input_type,
        "title_q": title_q,
        "country_q": country_q,
        "exclude_company": exclude_company or "",
        "market_company": market_company_in,
        "business_url": canonical_url or "",
        "company_email": company_email,
    }

    increment_guest_analyze_if_anonymous(session, user_raw, CARL4B2B_GUEST_ANALYZE_SESSION_KEY)
    guest_rem = None
    if not user_raw:
        guest_rem = guest_analyze_remaining(
            session,
            user=user_raw,
            count_key=CARL4B2B_GUEST_ANALYZE_SESSION_KEY,
            limit=CARL4B2B_GUEST_ANALYZE_LIMIT,
        )
    return api_success_response(
        {
            "analysis": analysis,
            "source": source,
            "profile_sync": profile_sync,
            "guest_analyzes_remaining": guest_rem,
        }
    )


@carl_business_bp.post("/chat")
def carl_business_chat():
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

    effective_message, pe_err = carl_business_effective_user_message(
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


# ─── Brave Search integration (external context only) ───────────────────────
# Never influences Ghost Score, Salary Drift, or any score. Explicit user clicks
# only. Per-session hard cap (BRAVE_SESSION_LIMIT). 24h in-memory cache shared
# across users. Silently disabled when BRAVE_SEARCH_API_KEY is unset.


def _build_brave_session_meta(
    analysis: Dict[str, Any],
    canonical_url: Optional[str],
    title_q: str,
    country_q: str,
) -> Dict[str, Any]:
    """Extract Brave-query hints from a freshly built analysis + input context."""
    matches = analysis.get("matches") if isinstance(analysis, dict) else None
    jobs = (matches or {}).get("jobs") if isinstance(matches, dict) else None
    company_names: List[str] = []
    if isinstance(jobs, list):
        for j in jobs:
            name = str((j or {}).get("company") or "").strip()
            if not name or name == "—":
                continue
            if name not in company_names:
                company_names.append(name)
            if len(company_names) >= 3:
                break

    company_hint = ""
    if canonical_url:
        try:
            host = urlparse(canonical_url).hostname or ""
        except Exception:
            host = ""
        company_hint = _brand_token_from_host(host).strip()
    if not company_hint and company_names:
        company_hint = company_names[0]

    return {
        "company": company_hint,
        "title": title_q or "",
        "country": country_q or "",
        "top_hirers": company_names,
    }


@carl_business_bp.post("/brave/context")
def carl_business_brave_context():
    """Fetch Brave Search external context for one of the 3 trigger buttons.

    Response shape:
        { status: "ok"|"limit_reached"|"unavailable"|"invalid_input",
          items: [...], remaining: int }

    The endpoint never affects scoring or persists anything to the database.
    """
    user = session.get("user")
    if not user:
        brave_meta = session.get("carl4b2b_brave_meta")
        if not isinstance(brave_meta, dict) or not brave_meta:
            return api_error_response("login_required", "Sign in to use this feature.", 401)
    if not csrf_valid():
        return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)

    payload = request.get_json(silent=True) or {}
    ctx_type = str(payload.get("context_type") or "").strip().lower()
    if ctx_type not in ("company", "role_market", "competitor"):
        return api_error_response("invalid_input", "Unknown context_type.", 400)

    meta = session.get("carl4b2b_brave_meta") or {}
    if not isinstance(meta, dict):
        meta = {}

    count = int(session.get("carl4b2b_brave_count") or 0)
    remaining_before = max(0, BRAVE_SESSION_LIMIT - count)
    if remaining_before <= 0:
        return api_success_response(
            {
                "status": "limit_reached",
                "items": [],
                "remaining": 0,
                "limit": BRAVE_SESSION_LIMIT,
            }
        )

    query = build_brave_query(ctx_type, meta)
    if not query:
        # Not enough input context for this trigger (e.g. no top hirers yet).
        return api_success_response(
            {
                "status": "unavailable",
                "items": [],
                "remaining": remaining_before,
                "limit": BRAVE_SESSION_LIMIT,
                "reason": "insufficient_context",
            }
        )

    results = fetch_brave_context(query)
    # Count every explicit click that reaches a backend call, cache hit or not.
    session["carl4b2b_brave_count"] = count + 1
    session.modified = True
    remaining_after = max(0, BRAVE_SESSION_LIMIT - (count + 1))

    if results is None:
        return api_success_response(
            {
                "status": "unavailable",
                "items": [],
                "remaining": remaining_after,
                "limit": BRAVE_SESSION_LIMIT,
                "reason": "upstream_unavailable",
            }
        )

    return api_success_response(
        {
            "status": "ok" if results else "no_results",
            "items": results,
            "remaining": remaining_after,
            "limit": BRAVE_SESSION_LIMIT,
            "contextType": ctx_type,
        }
    )


# =============================================================================
# CV Builder (Harvard-format DOCX)
# =============================================================================

cv_builder_bp = Blueprint("cv_builder", __name__)


@cv_builder_bp.get("/cv-builder")
def cv_builder_page():
    return render_template("account/cv_builder.html")


@cv_builder_bp.post("/cv-builder/generate")
def cv_builder_generate():
    """Accept CV upload or pasted text, return a Harvard-format .docx download."""
    if not csrf_valid():
        return api_error_response(
            "invalid_csrf", "Session expired. Please refresh and try again.", 400
        )

    upload = request.files.get("cv_file")
    text_fallback = (request.form.get("cv_text") or "").strip()
    has_file = bool(upload and (upload.filename or "").strip())

    if not has_file and not text_fallback:
        return api_error_response(
            "missing_input", "Upload a PDF or DOCX file, or paste your CV text.", 400
        )
    if has_file and text_fallback:
        return api_error_response(
            "conflicting_inputs",
            "Provide a file upload OR pasted text, not both.",
            400,
        )

    try:
        if has_file:
            extracted = extract_cv_from_upload(upload)
            cv_text = extracted.text
            stem = extracted.filename.rsplit(".", 1)[0]
            out_name = f"{stem}_harvard.docx"
        else:
            cv_text = normalize_cv_text(text_fallback)
            out_name = "cv_harvard.docx"
    except CVExtractionError as exc:
        return api_error_response(exc.code, exc.message, exc.status)

    try:
        data = extract_cv_structure(cv_text)
    except Exception as exc:  # pragma: no cover
        return api_error_response(
            "mapping_failed", f"CV structure extraction failed: {exc}", 500
        )

    try:
        docx_bytes = render_cv(data)
    except Exception as exc:  # pragma: no cover
        return api_error_response("render_failed", f"CV render failed: {exc}", 500)

    return send_file(
        io.BytesIO(docx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=out_name,
    )

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
        "carl/market_research_index.html",
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
    uid = user.get("id") if user else None
    # Returning from B2B or terminal "Menu" — show persona gate without embedding saved analysis.
    skip_preload = str(request.args.get("menu") or "").strip().lower() in ("1", "true", "yes", "pick")
    preloaded = None
    if user and not skip_preload and uid and SUPABASE_URL:
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

    guest_ctx = carl_guest_template_vars(session, user, limit=CARL_GUEST_ANALYZE_LIMIT)
    return render_template(
        "carl/carl.html",
        wide_layout=True,
        preloaded_analysis=preloaded,
        carl_company_industries=fetch_distinct_company_industries_for_carl(),
        **guest_ctx,
    )


@bp.post("/carl/analyze")
def carl_analyze():
    """Accept CV upload/text fallback and return deterministic mock analysis."""
    if not csrf_valid():
        return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)

    user_raw = session.get("user")
    quota_err = enforce_guest_analyze_quota(
        session,
        user_raw,
        count_key=CARL_GUEST_ANALYZE_SESSION_KEY,
        limit=CARL_GUEST_ANALYZE_LIMIT,
        register_url=url_for("auth.register"),
    )
    if quota_err:
        return quota_err

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

    user = user_raw or {}
    user_id = user.get("id")

    session_token = secrets.token_hex(16)
    session["carl_session_upload_id"] = session_token
    session.modified = True

    file_bytes_cache: Optional[bytes] = None
    if has_file and upload and (upload.filename or "").strip():
        try:
            upload.seek(0)
            file_bytes_cache = upload.read()
        except Exception as exc:
            logger.warning("Carl file read for storage skipped: %s", exc)

    cv_url = None
    storage_relpath = None
    if has_file and file_bytes_cache:
        try:
            fname = source.get("filename", "cv.pdf")
            if user_id:
                cv_url, storage_relpath = upload_cv_to_storage(
                    str(user_id), fname, file_bytes_cache
                )
                if cv_url:
                    docs = analysis.get("documents") or []
                    if docs:
                        docs[0]["subtitle"] = (
                            f"Vault · {source.get('filename')} · {source.get('byteSize', 0)} bytes"
                        )
                        docs[0]["badge"] = "Persistent"
            else:
                cv_url, storage_relpath = upload_cv_to_storage(
                    "",
                    fname,
                    file_bytes_cache,
                    path_prefix=f"anon/{session_token}",
                )
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
    if cv_url:
        persist_meta["carlCvPublicUrl"] = cv_url
    if not user_id and cv_url:
        persist_meta["anonCvPublicUrl"] = cv_url

    inferred_cty = _infer_country_from_cv_text(cv_text)
    ind_bucket = _infer_carl_industry_bucket(
        carl_snapshot["headline"],
        carl_snapshot["persona"],
        carl_snapshot["topSkillNames"],
    )

    if SUPABASE_URL:
        try:
            ins = insert_cv_upload_row(
                session_token,
                cv_text,
                persist_meta,
                user_id=str(user_id) if user_id else None,
                storage_path=storage_relpath,
                cv_analysis_full=analysis,
                inferred_title=carl_snapshot["headline"] or None,
                inferred_seniority=carl_snapshot.get("level") or None,
                top_skills=list(carl_snapshot.get("topSkillNames") or []),
                industry_bucket=ind_bucket,
                inferred_country=inferred_cty,
                consent_note="carl_cv_upload_v1",
            )
            if ins != "ok":
                logger.debug("Carl: cv_uploads insert status=%s", ins)
        except Exception as exc:
            logger.warning("Carl: cv_uploads insert skipped: %s", exc)

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
                cv_url=cv_url,
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
    increment_guest_analyze_if_anonymous(session, user_raw, CARL_GUEST_ANALYZE_SESSION_KEY)
    guest_rem = None
    if not user_raw:
        guest_rem = guest_analyze_remaining(
            session,
            user=user_raw,
            count_key=CARL_GUEST_ANALYZE_SESSION_KEY,
            limit=CARL_GUEST_ANALYZE_LIMIT,
        )
    return api_success_response(
        {
            "analysis": analysis,
            "source": source,
            "profile_sync": profile_sync,
            "guest_analyzes_remaining": guest_rem,
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
