"""Unified function/team taxonomy for job categorization.

Single source of truth: every module that needs to map a job title to a
function category imports ``categorize_function`` from here.

Previously duplicated in salary_analytics.py, explore.py, and career.py
with divergent keyword maps and label sets.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

FUNCTION_CATEGORIES: Dict[str, List[str]] = {
    "Backend": [
        "backend", "back-end", "back end", "server-side", "api engineer",
        "systems engineer", "golang", "java ", "python developer", "ruby",
        "software engineer", "software developer",
    ],
    "Frontend": [
        "frontend", "front-end", "front end", "react", "angular", "vue",
        "ui engineer", "ui developer", "css",
    ],
    "Fullstack": [
        "fullstack", "full-stack", "full stack",
    ],
    "ML/AI": [
        "machine learning", "ml ", "ml/", "ai ", "ai/",
        "artificial intelligence", "deep learning", "nlp",
        "computer vision", "llm",
    ],
    "Data": [
        "data engineer", "data scientist", "data analyst",
        "analytics engineer", "bi ", "business intelligence",
        "etl", "data platform", "dbt",
    ],
    "DevOps/Infra": [
        "devops", "sre", "site reliability", "infrastructure",
        "platform engineer", "cloud engineer", "kubernetes",
        "terraform", "aws engineer", "docker",
    ],
    "Security": [
        "security", "infosec", "cybersecurity", "appsec",
        "penetration", "soc",
    ],
    "Product": [
        "product manager", "product owner", "product lead",
        "product director", "scrum master", "agile",
    ],
    "Design": [
        "designer", "ux ", "ui/ux", "ux/ui", "design lead",
        "product design", "figma", "design system",
    ],
    "Management": [
        "engineering manager", "vp engineering", "cto",
        "head of engineering", "director of engineering",
        "tech lead manager", "vp engineer", "head of",
    ],
}

_CATEGORY_INDEX: List[Tuple[str, str]] = []
for _cat, _keywords in FUNCTION_CATEGORIES.items():
    for _kw in sorted(_keywords, key=len, reverse=True):
        _CATEGORY_INDEX.append((_kw, _cat))


def categorize_function(title_norm: str | None) -> str:
    """Map a normalized job title to a canonical function category.

    Returns one of the keys in ``FUNCTION_CATEGORIES`` or ``"Other"``.
    """
    if not title_norm:
        return "Other"
    t = title_norm.strip().lower()
    for keyword, category in _CATEGORY_INDEX:
        if keyword in t:
            return category
    return "Other"
