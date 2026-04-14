"""Extract structured CV data from plain text.

Primary path: Claude Haiku via Anthropic API (requires ANTHROPIC_API_KEY).
Fallback path: heuristic regex parser (no network, best-effort).
"""
from __future__ import annotations

import json
import os
import re
import urllib.request as _req
from typing import Any

# ── Claude API constants ─────────────────────────────────────────────────────

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 2048
_CV_CHARS = 15_000

_SYSTEM = (
    "You are a precise CV parser. Extract structured data and return ONLY valid JSON. "
    "No markdown, no explanation. Rewrite bullet points in Harvard action-verb format: "
    "strong past-tense verb + specific contribution + quantified result where inferable."
)

_SCHEMA = """{
  "name": "Full Name",
  "contact_line": "City, Country · email@example.com · +X XXX-XXXX",
  "education": [
    {
      "institution": "University Name",
      "location": "City, Country",
      "degree": "B.Sc. Computer Science, GPA 3.9",
      "dates": "Month Year",
      "coursework": "Course1, Course2",
      "thesis": "Title"
    }
  ],
  "experience": [
    {
      "org": "Organization Name",
      "location": "City, Country",
      "title": "Job Title",
      "dates": "Month Year – Month Year",
      "bullets": [
        "Action verb + specific contribution + result/metric"
      ]
    }
  ],
  "activities": [
    {
      "org": "Organization or Club Name",
      "location": "City, Country",
      "role": "Role Title",
      "dates": "Month Year – Month Year",
      "bullets": ["..."]
    }
  ],
  "skills": {
    "technical": "Python, SQL, React",
    "language": "English (Native), Spanish (B2)",
    "laboratory": "",
    "interests": "Photography, open-source"
  }
}"""


def extract_cv_structure(cv_text: str) -> dict:
    """Map CV plain text to a Harvard-template-compatible dict.

    Uses Claude Haiku when ANTHROPIC_API_KEY is set, otherwise falls back
    to the heuristic parser.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        return _extract_via_api(cv_text, api_key)
    return _extract_heuristic(cv_text)


# ── Claude API path ──────────────────────────────────────────────────────────

def _extract_via_api(cv_text: str, api_key: str) -> dict:
    prompt = (
        f"Parse the following CV into this exact JSON schema:\n{_SCHEMA}\n\n"
        "Rules:\n"
        "- education and experience in reverse chronological order\n"
        "- bullets: rewrite as Harvard action-verb format\n"
        "- contact_line: use · as separator\n"
        "- omit optional fields (coursework, thesis, laboratory) if absent — use empty string\n"
        "- return ONLY JSON, no markdown fences\n\n"
        f"CV TEXT:\n{cv_text[:_CV_CHARS]}"
    )
    payload = {
        "model": _MODEL,
        "max_tokens": _MAX_TOKENS,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }

    text: str | None = None
    try:
        import anthropic  # type: ignore

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(**payload)
        text = msg.content[0].text
    except ImportError:
        body = json.dumps(payload).encode()
        req = _req.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with _req.urlopen(req, timeout=30) as resp:
            text = json.loads(resp.read())["content"][0]["text"]

    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.split("```")[0]
    return json.loads(raw.strip())


# ── Heuristic fallback ───────────────────────────────────────────────────────

_SECTION_PATTERNS = {
    "education": re.compile(r"^education", re.I),
    "experience": re.compile(r"^(experience|work experience|employment|professional experience)", re.I),
    "activities": re.compile(r"^(activities|leadership|volunteering|extra.?curricular)", re.I),
    "skills": re.compile(r"^(skills|competencies|technical skills|skills & interests)", re.I),
    "contact": re.compile(r"^(contact|personal details|profile)", re.I),
}
_BULLET_RE = re.compile(r"^[\•\-\*\u2022\u25cf]\s+")
_DATE_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s,]+\d{4}"
    r"|(\d{4})\s*[–\-—]\s*(\d{4}|present|current)",
    re.I,
)


def _strip_bullet(line: str) -> str:
    return _BULLET_RE.sub("", line).strip()


def _is_bullet(line: str) -> bool:
    return bool(_BULLET_RE.match(line))


def _split_sections(text: str) -> dict[str, list[str]]:
    lines = [l.rstrip() for l in text.splitlines()]
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in lines:
        stripped = line.strip()
        matched = False
        for name, pat in _SECTION_PATTERNS.items():
            if pat.match(stripped) and len(stripped) < 60:
                current = name
                sections.setdefault(current, [])
                matched = True
                break
        if not matched:
            sections.setdefault(current, []).append(line)
    return sections


def _parse_header(lines: list[str]) -> tuple[str, str]:
    non_empty = [l.strip() for l in lines if l.strip()]
    name = non_empty[0] if non_empty else ""
    contact_parts = []
    for l in non_empty[1:]:
        if any(c in l for c in ("@", "+", "·", "|", ",")) or re.search(r"\d{4,}", l):
            contact_parts.append(l)
    contact_line = " · ".join(contact_parts) if contact_parts else " · ".join(non_empty[1:3])
    return name, contact_line


def _parse_entries(lines: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_bullet(stripped):
            if current is None:
                current = {"org": "", "location": "", "title": "", "dates": "", "bullets": []}
                entries.append(current)
            current.setdefault("bullets", []).append(_strip_bullet(stripped))
        else:
            entry_complete = current is not None and bool(current.get("title") or current.get("dates"))
            if current is None or entry_complete:
                current = {"org": stripped, "location": "", "title": "", "dates": "", "bullets": []}
                entries.append(current)
                parts = re.split(r"\s*[,|·]\s*", stripped, maxsplit=1)
                if len(parts) == 2:
                    current["org"] = parts[0].strip()
                    current["location"] = parts[1].strip()
            else:
                date_match = _DATE_RE.search(stripped)
                if date_match:
                    current["dates"] = date_match.group(0)
                    title_part = stripped[: date_match.start()].strip(" –-—")
                    current["title"] = title_part or current.get("title", "")
                else:
                    current["title"] = stripped
    return entries


def _parse_skills(lines: list[str]) -> dict[str, str]:
    skills: dict[str, str] = {"technical": "", "language": "", "laboratory": "", "interests": ""}
    label_map = {
        "technical": "technical",
        "tech": "technical",
        "programming": "technical",
        "software": "technical",
        "language": "language",
        "languages": "language",
        "lab": "laboratory",
        "laboratory": "laboratory",
        "interest": "interests",
        "interests": "interests",
        "hobbies": "interests",
    }
    ungrouped: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        colon_pos = stripped.find(":")
        if colon_pos != -1:
            label_raw = stripped[:colon_pos].strip().lower()
            value = stripped[colon_pos + 1 :].strip()
            bucket = label_map.get(label_raw)
            if bucket:
                skills[bucket] = value
                continue
        ungrouped.append(_strip_bullet(stripped) if _is_bullet(stripped) else stripped)
    if ungrouped and not skills["technical"]:
        skills["technical"] = ", ".join(ungrouped)
    return skills


def _extract_heuristic(cv_text: str) -> dict:
    """Best-effort heuristic parser — no network calls."""
    sections = _split_sections(cv_text)
    name, contact_line = _parse_header(sections.get("header", []))

    edu_entries = _parse_entries(sections.get("education", []))
    education = [
        {
            "institution": e.get("org", ""),
            "location": e.get("location", ""),
            "degree": e.get("title", ""),
            "dates": e.get("dates", ""),
            "coursework": "",
            "thesis": "",
        }
        for e in edu_entries
    ]

    exp_entries = _parse_entries(sections.get("experience", []))
    experience = [
        {
            "org": e.get("org", ""),
            "location": e.get("location", ""),
            "title": e.get("title", ""),
            "dates": e.get("dates", ""),
            "bullets": e.get("bullets", []),
        }
        for e in exp_entries
    ]

    act_entries = _parse_entries(sections.get("activities", []))
    activities = [
        {
            "org": e.get("org", ""),
            "location": e.get("location", ""),
            "role": e.get("title", ""),
            "dates": e.get("dates", ""),
            "bullets": e.get("bullets", []),
        }
        for e in act_entries
    ]

    return {
        "name": name,
        "contact_line": contact_line,
        "education": education,
        "experience": experience,
        "activities": activities,
        "skills": _parse_skills(sections.get("skills", [])),
    }
