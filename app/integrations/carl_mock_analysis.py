"""Deterministic mock analyzer powering the Carl CV dashboard."""

from __future__ import annotations

import hashlib
import random
import re
from typing import Any, Optional, Sequence

from ..config import CARL_CHAT_MAX_REPLY_CHARS

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
        base = 45 + (12 if key in text_lower else 0)
        bonus = rng.randint(8, 38)
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
