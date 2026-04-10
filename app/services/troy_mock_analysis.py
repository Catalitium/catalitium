"""Deterministic mock analyzer powering the TROY demo dashboard."""

from __future__ import annotations

import hashlib
import random
import re
from typing import Any

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
    terminal_logs = _build_terminal_logs(file_label, ats_score, strengths, risk_flags)

    structure_score = min(100, 48 + min(len(words) // 25, 28))
    impact_score = min(
        100,
        52
        + (18 if "%" in text_lower or "increased" in text_lower or "reduced" in text_lower else 0)
        + min(years * 2, 20),
    )
    narrative_score = min(100, 44 + min(len(unique_words) // 12, 30))

    headline = f"{level} {persona} profile with {keyword_coverage}% ATS keyword coverage"
    fit_summary = (
        f"CV shows {years}+ years of relevant signal with strongest evidence in "
        f"{', '.join(s['skill'] for s in top_skills[:3])}."
    )

    documents = [
        {"title": "CV intelligence", "subtitle": f"Source · {file_label}", "badge": "New"},
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
            "summary": f"{headline}. Focus next revision on measurable outcomes and missing ATS terms.",
            "suggestedPrompts": [
                "How can I increase my ATS score quickly?",
                "Rewrite my profile summary for hiring managers.",
                "What bullet points should I add for impact?",
            ],
        },
    }


def generate_chat_reply(message: str, chat_context: dict[str, Any]) -> str:
    """Generate a deterministic rule-based chat reply."""
    prompt = (message or "").strip().lower()
    if not prompt:
        return "Share one question about your CV and I will suggest specific improvements."

    missing_keywords = chat_context.get("missingKeywords") or []
    summary = str(chat_context.get("summary") or "").strip()

    if "ats" in prompt or "score" in prompt:
        if missing_keywords:
            return (
                "Fast ATS win: include these missing keywords in context-based bullet points: "
                + ", ".join(missing_keywords[:4])
                + "."
            )
        return "Your ATS signal is strong. Next gain comes from quantifying outcomes in each experience bullet."
    if "rewrite" in prompt or "summary" in prompt:
        return (
            "Suggested summary: Results-driven professional with a track record of delivering measurable impact, "
            "cross-functional execution, and strong ownership across complex initiatives."
        )
    if "risk" in prompt or "weak" in prompt or "gap" in prompt:
        if missing_keywords:
            return "Main risk is keyword coverage gaps in: " + ", ".join(missing_keywords[:3]) + "."
        return "Main risk is low quantified impact. Add metrics, percentages, or revenue/cost outcomes per role."
    return summary or "I analyzed your CV. Ask about ATS, bullet rewriting, or risk flags for concrete guidance."


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


def _build_terminal_logs(
    file_label: str,
    ats_score: int,
    strengths: list[str],
    risk_flags: list[str],
) -> list[str]:
    logs = [
        f"[TROY] ingest: {file_label}",
        "[TROY] parser: extracting CV text blocks",
        "[TROY] feature-map: computing skills and timeline vectors",
        f"[TROY] ats-estimator: score={ats_score}",
        f"[TROY] strengths: {strengths[0]}",
    ]
    if risk_flags:
        logs.append(f"[TROY] risk: {risk_flags[0]}")
    logs.append("[TROY] ready: dashboard payload assembled")
    return logs
