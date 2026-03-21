"""Flask application entry point and route definitions for Catalitium."""

import os
import re
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional, Dict, Any, List
from urllib.parse import urlparse

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    g,
    Response,
    send_from_directory,
    abort,
    after_this_request,
    session,
)
from email_validator import validate_email, EmailNotValidError
from .models.db import (
    SECRET_KEY,
    SUPABASE_URL,
    PER_PAGE_MAX,
    logger,
    close_db,
    init_db,
    get_db,
    get_salary_for_location,
    normalize_country,
    normalize_title,
    parse_salary_query,
    parse_salary_range_string,
    parse_job_description,
    format_job_date_string,
    clean_job_description_text,
    insert_subscriber,
    insert_contact,
    insert_job_posting,
    get_job_summary,
    save_job_summary,
    create_api_key,
    get_api_key_by_email,
    confirm_api_key_by_token,
    revoke_api_key,
    check_and_increment_api_key,
    Job,
    insert_stripe_order,
    mark_stripe_order_paid,
    mark_stripe_order_job_submitted,
    get_stripe_order,
    upsert_user_subscription,
    get_user_subscriptions,
    get_subscription_by_stripe_id,
    update_api_key_limit_by_email,
)

try:
    import stripe as _stripe
except ImportError:
    _stripe = None  # type: ignore[assignment]
import json as _json
import urllib.request as _urllib_req
import hashlib
import secrets
import functools
import smtplib
from email.mime.text import MIMEText
from werkzeug.middleware.proxy_fix import ProxyFix
from .api_utils import (
    TTLCache,
    api_fail,
    api_ok,
    generate_request_id,
    parse_int_arg,
    parse_str_arg,
)

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except Exception:  # pragma: no cover
    Limiter = None  # type: ignore[assignment]
    get_remote_address = None  # type: ignore[assignment]

try:
    from flask_compress import Compress as _Compress
except Exception:  # pragma: no cover
    _Compress = None  # type: ignore[assignment]

try:
    from supabase import create_client as _sb_create_client
except ImportError:
    _sb_create_client = None

_supabase_client = None        # used for sign_in / sign_up
_supabase_admin_client = None  # used only for admin.* calls — never stores a user session

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


def _get_supabase():
    """Return the shared auth client (sign_in, sign_up)."""
    global _supabase_client
    if _supabase_client is None and _sb_create_client:
        project_url = _derive_supabase_project_url()
        key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if not project_url or not key:
            logger.warning("Supabase auth client unavailable: missing SUPABASE_PROJECT_URL or SUPABASE_SECRET_KEY")
            return None
        try:
            _supabase_client = _sb_create_client(project_url, key)
        except Exception as exc:
            logger.warning("Supabase auth client init failed: %s", exc)
            return None
    return _supabase_client


def _get_supabase_admin():
    """Return a dedicated admin client that is never used for sign_in/sign_up,
    so its internal session is never overwritten and admin.* calls always work."""
    global _supabase_admin_client
    if _supabase_admin_client is None and _sb_create_client:
        project_url = _derive_supabase_project_url()
        key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if not project_url or not key:
            logger.warning("Supabase admin client unavailable: missing SUPABASE_PROJECT_URL or SUPABASE_SECRET_KEY")
            return None
        try:
            _supabase_admin_client = _sb_create_client(project_url, key)
        except Exception as exc:
            logger.warning("Supabase admin client init failed: %s", exc)
            return None
    return _supabase_admin_client


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


def _get_mi_tier(user: Optional[Dict]) -> str:
    """Return the user's active Market Intelligence tier: 'pro', 'premium', or 'free'."""
    if not user:
        return "free"
    subs = get_user_subscriptions(user.get("id", ""))
    mi = subs.get("market_intelligence")
    if mi and mi.get("status") == "active" and mi.get("tier") in ("premium", "pro"):
        return mi["tier"]
    return "free"


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


def _slugify(text: str) -> str:
    """Convert job title text to a URL-safe slug (max 60 chars)."""
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:60]


_CATEGORY_CONTEXTS = {
    "ai": {
        "headline": "AI & Machine Learning Jobs",
        "intro": "AI and machine learning roles are the fastest-growing segment in tech, commanding 15–25% higher salaries than the general developer average. Roles span LLM engineering, MLOps, computer vision, NLP, data science, and applied AI research.",
        "salary_note": "Typical range: $130k–$200k USD &middot; &euro;100k–&euro;160k EUR",
    },
    "developer": {
        "headline": "Software Developer & Engineer Jobs",
        "intro": "Software development remains the largest category in tech hiring globally. Whether you specialise in full-stack, backend, frontend, mobile or DevOps, demand for strong engineers continues to outpace supply across all major markets.",
        "salary_note": "Typical range: $100k–$165k USD &middot; &euro;65k–&euro;110k EUR",
    },
    "remote": {
        "headline": "Remote-First Tech Jobs",
        "intro": "Remote tech roles have grown over 30% year-on-year. While base salaries may be 8–12% below equivalent on-site roles, the effective purchasing power is often significantly higher for candidates based in lower-cost regions.",
        "salary_note": "Typical range: $90k–$155k USD &middot; &euro;55k–&euro;95k EUR",
    },
    "senior": {
        "headline": "Senior, Lead & Principal Engineer Roles",
        "intro": "Senior roles typically require 5+ years of experience and command a significant compensation premium. Leadership scope, system design ownership, and cross-functional influence are the differentiators at this level.",
        "salary_note": "Typical range: $140k–$210k USD &middot; &euro;90k–&euro;135k EUR",
    },
    "eu": {
        "headline": "Tech Jobs in Europe",
        "intro": "The EU tech market is concentrated around hubs in Germany (Berlin, Munich), France (Paris), Netherlands (Amsterdam), Spain (Barcelona, Madrid), and Switzerland (Zurich). Salaries are quoted in local currency and normalised to EUR.",
        "salary_note": "Typical range: &euro;60k–&euro;120k EUR &middot; CHF 90k–CHF 145k",
    },
    "us": {
        "headline": "Tech Jobs in the United States",
        "intro": "The US remains the highest-paying market for tech globally. Major hubs include the San Francisco Bay Area, New York, Seattle, Austin, and Boston — alongside fully remote-first companies headquartered across the country.",
        "salary_note": "Typical range: $110k–$185k USD",
    },
    "uk": {
        "headline": "Tech Jobs in the United Kingdom",
        "intro": "London leads UK tech hiring, followed by Manchester, Edinburgh, and Bristol. The UK market features strong fintech, media, and deep-tech sectors, with competitive compensation relative to European peers.",
        "salary_note": "Typical range: &pound;62k–&pound;115k GBP",
    },
    "ch": {
        "headline": "Tech Jobs in Switzerland",
        "intro": "Switzerland offers some of the highest tech salaries in Europe, concentrated in Zurich, Geneva, and Basel. The market favours senior engineering, fintech, pharmatech, and multilingual professionals.",
        "salary_note": "Typical range: CHF 100k–CHF 165k",
    },
    "data": {
        "headline": "Data Science & Analytics Jobs",
        "intro": "Data science roles bridge statistics, programming, and business intelligence. Demand is strong across all sectors — from fintech to e-commerce — with Python, SQL, and cloud data platforms (Snowflake, BigQuery, dbt) as the core stack.",
        "salary_note": "Typical range: $110k–$170k USD &middot; &euro;75k–&euro;120k EUR",
    },
}


def _get_category_context(title_q: str, country_q: str) -> Optional[Dict]:
    """Return editorial context dict for the active search, or None if no match."""
    t = (title_q or "").lower()
    c = (country_q or "").lower()
    for key in (t, c):
        if key in _CATEGORY_CONTEXTS:
            return _CATEGORY_CONTEXTS[key]
    # Partial matches for compound searches (e.g. "senior developer")
    for key, ctx in _CATEGORY_CONTEXTS.items():
        if key in t:
            return ctx
    return None


def _query_tokens(value: str) -> set[str]:
    """Return normalized search tokens used for lightweight match scoring."""
    return {tok for tok in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(tok) > 1}


def _salary_band_label(sal_floor: Optional[int], sal_ceiling: Optional[int]) -> str:
    """Return a compact salary filter label for subscription context."""
    if sal_floor and sal_ceiling:
        return f"{int(sal_floor/1000)}k-{int(sal_ceiling/1000)}k"
    if sal_floor:
        return f"{int(sal_floor/1000)}k+"
    if sal_ceiling:
        return f"Up to {int(sal_ceiling/1000)}k"
    return ""


def _compute_match_score(
    *,
    job_title: str,
    job_location: str,
    query_title: str,
    query_country: str,
    has_salary: bool,
    has_apply_link: bool,
) -> tuple[int, list[str]]:
    """Return a simple, explainable match score and up to 3 trust/match reasons."""
    score = 35
    reasons: list[str] = []

    title_tokens = _query_tokens(query_title)
    job_title_tokens = _query_tokens(job_title)
    if title_tokens:
        overlap = len(title_tokens & job_title_tokens)
        coverage = overlap / max(1, len(title_tokens))
        score += int(round(coverage * 35))
        if overlap:
            reasons.append("Title matches your search")

    q_country = (query_country or "").strip().lower()
    loc = (job_location or "").lower()
    if q_country:
        if q_country == "high_pay":
            score += 10
            reasons.append("High-pay market focus")
        elif q_country in loc:
            score += 20
            reasons.append("Location matches your filter")
        else:
            score -= 6

    if has_salary:
        score += 12
        reasons.append("Salary estimate available")

    if "remote" in loc:
        score += 6
        reasons.append("Remote-friendly listing")

    if has_apply_link:
        score += 5
        reasons.append("Direct apply link")

    score = max(25, min(99, score))
    # Keep 3 concise reasons prioritizing relevance/trust.
    return score, reasons[:3]


def _is_safe_redirect_target(target: str) -> bool:
    """Allow only relative URLs or absolute http(s) URLs."""
    if not target:
        return False
    parsed = urlparse(target.strip())
    if not parsed.scheme and not parsed.netloc:
        # Relative path like /jobs/123
        return target.startswith("/")
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        return True
    return False


def _call_anthropic(description: str, api_key: str):
    """Call Claude Haiku to extract 3 bullets + up to 8 skill tags from a job description.

    Returns (bullets: list[str], skills: list[str]) or (None, None) on failure.
    Tries the anthropic SDK first; falls back to raw urllib.request.
    """
    prompt = (
        "Analyze this job description and return ONLY valid JSON (no markdown, no extra text):\n"
        '{"bullets":["What you\'ll do in 1 sentence","What you need: key skills/exp in 1 sentence","What you get: comp/perks in 1 sentence"],'
        '"skills":["Skill1","Skill2",...up to 8 tech skills or tools]}\n\n'
        f"Job description:\n{description[:3000]}"
    )
    text = None
    try:
        import anthropic  # type: ignore
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text
    except ImportError:
        # Fallback: raw HTTP
        try:
            body = _json.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = _urllib_req.Request(
                "https://api.anthropic.com/v1/messages",
                data=body,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                method="POST",
            )
            with _urllib_req.urlopen(req, timeout=20) as resp:
                result = _json.loads(resp.read())
                text = result["content"][0]["text"]
        except Exception as exc:
            logger.warning("Anthropic urllib fallback failed: %s", exc)
            return None, None
    except Exception as exc:
        logger.warning("Anthropic SDK call failed: %s", exc)
        return None, None

    if not text:
        return None, None

    try:
        clean = re.sub(r"^```json?\s*", "", text.strip(), flags=re.MULTILINE)
        clean = re.sub(r"```\s*$", "", clean.strip(), flags=re.MULTILINE)
        parsed = _json.loads(clean)
        bullets = [str(b) for b in (parsed.get("bullets") or [])[:3]]
        skills  = [str(s) for s in (parsed.get("skills")  or [])[:8]]
        return bullets, skills
    except Exception as exc:
        logger.warning("Failed to parse Anthropic response: %s | raw: %.200s", exc, text)
        return None, None


BLACKLIST_LINKS = {
    "https://example.com/job/1",
}

TITLE_BUCKET2_KEYWORDS = (
    "principal",
    "staff",
    "lead ",
    "lead-",
    "head of",
    "director",
)

TITLE_BUCKET1_KEYWORDS = (
    "senior",
    "sr ",
    "sr.",
    "expert",
)

ENVIRONMENT = os.getenv("FLASK_ENV") or os.getenv("ENV") or "production"

def _get_demo_jobs():
    """Return demo jobs for empty search results."""
    return [
        {
            "id": f"demo-{i}",
            "title": title,
            "company": company,
            "location": location,
            "description": desc,
            "date_posted": date,
            "link": "",
            "is_new": False,
        }
        for i, (title, company, location, desc, date) in enumerate(
            [
                (
                    "Senior Software Engineer (AI)",
                    "Catalitium",
                    "Remote / EU",
                    "Own end-to-end features across ingestion, ranking, and AI-assisted matching.",
                    "2025.10.01",
                ),
                (
                    "Data Engineer",
                    "Catalitium",
                    "London, UK",
                    "Build reliable pipelines and optimize warehouse performance.",
                    "2025.09.28",
                ),
                (
                    "Product Manager",
                    "Stealth",
                    "Zurich, CH",
                    "Partner with design and engineering to deliver user value quickly.",
                    "2025.09.27",
                ),
                (
                    "Frontend Developer",
                    "Acme Corp",
                    "Barcelona, ES",
                    "Ship delightful UI with Tailwind and strong accessibility.",
                    "2025.09.26",
                ),
                (
                    "Cloud DevOps Engineer",
                    "Nimbus",
                    "Remote / Europe",
                    "Automate infrastructure, observability, and release workflows.",
                    "2025.09.25",
                ),
                (
                    "ML Engineer",
                    "Quantix",
                    "Remote",
                    "Deploy ranking and semantic matching at scale.",
                    "2025.09.24",
                ),
            ],
            start=1,
        )
    ]

REPORTS = [
    {
        "slug": "global-tech-ai-careers-report-2026",
        "title": "Catalitium Global Tech & AI Careers Report - 2026 Edition",
        "short_title": "Global Tech & AI Careers Report 2026",
        "description": (
            "Data-driven analysis of AI's impact on tech jobs, skills in demand, "
            "salaries by region (US, Europe, India), and the fastest growing roles for 2025-2026."
        ),
        "published": "2025-11-01",
        "published_display": "November 2025",
        "pdf_path": "reports/R01- Catalitium Global Tech & AI Careers Report  November 2025 Edition.pdf",
        "read_time": "12 min read",
        "keywords": [
            "global tech and AI jobs report 2026",
            "AI careers report 2026",
            "tech skills in demand 2025",
            "AI job market trends",
            "2025 tech salaries US Europe India",
            "remote and hybrid work trends in tech",
            "fastest growing AI jobs 2025 2026",
        ],
    },
    {
        "slug": "200k-engineer-ai-reshaping-software-salaries-2026",
        "title": "The $200K Engineer: How AI Productivity Is Reshaping Software Salaries",
        "short_title": "The $200K Engineer Report 2026",
        "description": (
            "Staff engineers saw 7.52% comp growth while junior hiring collapsed 73%. "
            "A data-driven investigation into who wins, who loses, and what drives the split "
            "in software engineering compensation in 2025\u20132026. 69 sources."
        ),
        "published": "2026-02-01",
        "published_display": "February 2026",
        "pdf_path": "",
        "read_time": "18 min read",
        "gated": True,
        "template": "reports/200k_engineer.html",
        "keywords": [
            "software engineer salary 2026",
            "AI skills salary premium",
            "staff engineer compensation growth",
            "junior developer hiring collapse 2025",
            "AI productivity compensation bifurcation",
            "Anthropic OpenAI engineer salary",
            "revenue per employee software companies",
            "software engineering salary trends 2026",
        ],
    },
    {
        "slug": "from-saas-to-agents-ai-native-workforce-2026",
        "title": "From SaaS to Agents: How AI Native Software Is Reshaping the Tech Workforce",
        "short_title": "From SaaS to Agents Report 2026",
        "description": (
            "A data-driven investigation into team economics, revenue per employee, AI-agent adoption, "
            "and the structural transformation of software work. 74 sources, February 2026."
        ),
        "published": "2026-02-01",
        "published_display": "February 2026",
        "pdf_path": "",
        "read_time": "20 min read",
        "gated": True,
        "template": "reports/saas_to_agents.html",
        "keywords": [
            "AI native software workforce 2026",
            "revenue per employee AI companies",
            "SaaS to agents transition",
            "AI engineer hiring demand 2026",
            "software developer job market decline",
            "GitHub Copilot productivity study",
            "enterprise AI adoption transformation gap",
            "Klarna AI workforce case study",
        ],
    },
    {
        "slug": "ai-productivity-paradox-junior-roles-2026",
        "title": "AI Didn\u2019t Kill Jobs \u2014 It Killed Junior Roles",
        "short_title": "AI Productivity Paradox Report 2026",
        "description": (
            "Entry-level tech job postings dropped 35% since 2023 while AI engineers earn $206K on average. "
            "Data-driven analysis of how AI productivity tools are reshaping the tech labor market, "
            "collapsing junior demand, and creating an unprecedented senior skill premium."
        ),
        "published": "2025-12-01",
        "published_display": "December 2025",
        "pdf_path": "reports/R02- AI Didn\u2019t Kill Jobs \u2014 It Killed Junior Roles.pdf",
        "read_time": "15 min read",
        "template": "reports/junior_roles.html",
        "keywords": [
            "entry level tech jobs 2026",
            "AI productivity paradox",
            "junior developer jobs decline",
            "AI skill salary premium 2025",
            "tech hiring trends 2026",
            "github copilot adoption stats",
            "series A team size decline",
            "CS degree unemployment 2025",
        ],
    },
    {
        "slug": "death-of-saas-vibecoding-2026",
        "title": "The Death of SaaS: How Vibecoding Is Killing a $315 Billion Industry",
        "short_title": "The Death of SaaS Report 2026",
        "description": (
            "A data-driven market report analyzing how AI-assisted development is structurally "
            "disrupting the $315 billion SaaS industry — with sourced data from a16z, Gartner, "
            "YC, Retool, Deloitte, and Emergence Capital."
        ),
        "published": "2026-02-01",
        "published_display": "February 2026",
        "pdf_path": "reports/R03- The Death of SaaS How Vibecoding Is Killing a 315 Billion Industry.pdf",
        "read_time": "18 min read",
        "gated": True,
        "template": "reports/saas_vibecoding.html",
        "keywords": [
            "death of saas 2026",
            "vibecoding saas disruption",
            "ai coding tools market report",
            "build vs buy saas 2026",
            "saas market size 2026",
            "cursor ai growth",
            "ai native saas vs traditional saas",
            "software as labor business model",
        ],
    },
]


def _send_mail(to: str, subject: str, body: str) -> None:
    """Send a plain-text email via SMTP. Best-effort; logs on failure, never raises."""
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    pw = os.getenv("SMTP_PASS", "").strip()
    frm = os.getenv("SMTP_FROM", "noreply@catalitium.com").strip()
    if not host:
        logger.warning("_send_mail: SMTP_HOST not configured, skipping email to %s", to)
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = frm
        msg["To"] = to
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            if user:
                s.login(user, pw)
            s.send_message(msg)
    except Exception as exc:
        logger.warning("_send_mail failed (to=%s): %s", to, exc)


def _send_subscribe_confirmation(email: str, focus: str = "") -> None:
    """Send a welcome confirmation email to a new subscriber."""
    focus_line = f"\nYour focus: {focus}\n" if focus else ""
    body = f"""Welcome to Catalitium.

You're now on the weekly high-match digest.{focus_line}
Every week we send you the highest-signal tech jobs with real salary data — no noise, no spam.

Browse jobs now: {os.getenv("BASE_URL", "https://catalitium.com")}

--
Catalitium | info@catalitium.com
Unsubscribe: {os.getenv("BASE_URL", "https://catalitium.com")}/unsubscribe
"""
    _send_mail(email, "You're on the Catalitium weekly digest", body)


_sitemap_cache: dict = {"data": None, "ts": 0.0}


def create_app() -> Flask:
    """Instantiate and configure the Flask application."""
    app = Flask(__name__, template_folder="views/templates")
    env = ENVIRONMENT or "production"
    if env == "production":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)  # type: ignore[assignment]

    if not SUPABASE_URL:
        logger.error("SUPABASE_URL (or DATABASE_URL) must be configured before starting the app.")
        raise SystemExit(1)

    asset_version = (os.getenv("ASSET_VERSION") or "20260320-stability1").strip() or "20260320-stability1"
    app.config.update(
        SECRET_KEY=SECRET_KEY,
        TEMPLATES_AUTO_RELOAD=(env != "production"),
        PER_PAGE_MAX=PER_PAGE_MAX,
        SUPABASE_URL=SUPABASE_URL,
        ASSET_VERSION=asset_version,
        MAX_CONTENT_LENGTH=int(os.getenv("MAX_CONTENT_LENGTH", "1048576")),  # 1MB default
        # Keep secure cookies in production, but allow local HTTP dev
        # (127.0.0.1/localhost) so session + CSRF flows work on /register.
        SESSION_COOKIE_SECURE=(env == "production"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    trusted_hosts_env = os.getenv("TRUSTED_HOSTS", "").strip()
    if trusted_hosts_env:
        app.config["TRUSTED_HOSTS"] = [h.strip() for h in trusted_hosts_env.split(",") if h.strip()]
    app.teardown_appcontext(close_db)
    if _Compress is not None:
        app.config.setdefault("COMPRESS_ALGORITHM", ["br", "gzip"])
        _Compress(app)
    limiter = None
    if Limiter is not None and get_remote_address is not None:
        limiter = Limiter(
            key_func=get_remote_address,
            app=app,
            default_limits=[os.getenv("RATE_LIMIT_DEFAULT", "240 per minute")],
            storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
            strategy="fixed-window",
        )
    else:
        logger.warning("flask-limiter not installed or failed to import; rate limiting is disabled")

    summary_cache = TTLCache(ttl_seconds=90, max_size=400)
    autocomplete_cache = TTLCache(ttl_seconds=120, max_size=400)
    salary_insights_cache = TTLCache(ttl_seconds=120, max_size=250)

    @app.before_request
    def assign_request_id():
        g.request_id = generate_request_id()

    def _csrf_token() -> str:
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return str(token)

    @app.context_processor
    def inject_csrf_token():
        host = (request.host or "").split(":", 1)[0].lower()
        is_local_host = host in {"127.0.0.1", "localhost", "0.0.0.0"}
        return {
            "csrf_token": _csrf_token,
            "asset_version": app.config.get("ASSET_VERSION", "dev"),
            # Treat localhost as non-production even when ENV defaults to production.
            "is_production_env": (env == "production" and not is_local_host),
        }

    def _csrf_valid() -> bool:
        expected = str(session.get("_csrf_token") or "")
        provided = (
            request.form.get("csrf_token")
            or request.headers.get("X-CSRF-Token")
            or ""
        ).strip()
        if not expected or not provided:
            return False
        return secrets.compare_digest(expected, provided)

    def _api_request() -> bool:
        path = request.path or ""
        return path.startswith("/api/") or path.startswith("/v1/") or request.is_json

    def _api_success(data: Dict[str, Any], status: int = 200, code: str = "ok", message: str = "ok"):
        return jsonify(
            api_ok(
                data=data,
                request_id=getattr(g, "request_id", ""),
                code=code,
                message=message,
            )
        ), status

    def _api_error(code: str, message: str, status: int = 400, details: Optional[Dict[str, Any]] = None):
        return jsonify(
            api_fail(
                code=code,
                message=message,
                request_id=getattr(g, "request_id", ""),
                details=details or {},
            )
        ), status

    def _resolve_pagination(default_per_page: int = 12) -> Tuple[int, int]:
        """Return (page, per_page_limit) constrained to safe bounds."""
        per_page = parse_int_arg(
            request.args,
            "per_page",
            default=default_per_page,
            minimum=1,
            maximum=int(app.config.get("PER_PAGE_MAX", 100)),
        )
        page = parse_int_arg(request.args, "page", default=1, minimum=1, maximum=10_000)
        return page, per_page

    def _display_per_page(per_page: int) -> int:
        """Return the value surfaced in pagination metadata."""
        if per_page < 5:
            return per_page
        return max(per_page, 10)

    def _limit(rule: str):
        """Apply rate limit only when flask-limiter is available."""
        def _decorator(fn):
            if limiter is None:
                return fn
            return limiter.limit(rule)(fn)
        return _decorator

    def _require_api_key(f):
        """Decorator: validate X-API-Key header, enforce monthly quota, inject rate-limit headers."""
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            raw_key = (
                request.headers.get("X-API-Key")
                or request.args.get("api_key")
                or ""
            ).strip()
            if not raw_key:
                return jsonify({"error": "invalid_key"}), 401
            key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
            now = datetime.now(timezone.utc)
            usage = check_and_increment_api_key(key_hash, now)
            if usage is None:
                return jsonify({"error": "invalid_key"}), 401
            if isinstance(usage, dict) and usage.get("error") == "quota_exceeded":
                return jsonify({"error": "quota_exceeded"}), 429
            g.api_key_record = usage

            @after_this_request
            def _inject_ratelimit_headers(response):
                rec = g.get("api_key_record", {})
                limit = rec.get("monthly_limit", 0)
                used = rec.get("requests_this_month", 0)
                _now = datetime.now(timezone.utc)
                if _now.month == 12:
                    reset_dt = _now.replace(year=_now.year + 1, month=1, day=1,
                                            hour=0, minute=0, second=0, microsecond=0)
                else:
                    reset_dt = _now.replace(month=_now.month + 1, day=1,
                                            hour=0, minute=0, second=0, microsecond=0)
                response.headers["X-RateLimit-Limit"] = str(limit)
                response.headers["X-RateLimit-Remaining"] = str(max(0, limit - used))
                response.headers["X-RateLimit-Reset"] = reset_dt.isoformat()
                response.headers["X-RateLimit-Window"] = "monthly"
                return response

            return f(*args, **kwargs)
        return decorated

    @app.after_request
    def apply_analytics_cookie(response):
        """Ensure the analytics session cookie is propagated when a new ID is issued."""
        sid_info = getattr(g, "_analytics_sid_new", None)
        if sid_info:
            cookie_name, sid = sid_info
            secure_cookie = env == "production"
            response.set_cookie(
                cookie_name,
                sid,
                max_age=31536000,
                httponly=True,
                samesite="Lax",
                secure=secure_cookie,
            )
        # Lightweight caching headers: long-cache static assets, short-cache everything else
        try:
            path = request.path or ""
            content_type = (response.content_type or "").lower()
            html_response = "text/html" in content_type
            auth_ui_paths = {
                "/register",
                "/studio",
                "/profile",
                "/hire",
                "/hire/onboarding",
            }
            if path.startswith("/static/"):
                # 30d cache for versioned static files; adjust if assets aren't fingerprinted
                response.headers.setdefault("Cache-Control", "public, max-age=2592000, immutable")
            elif path.startswith("/api/") or path.startswith("/v1/"):
                # API responses must not be publicly cached
                response.headers["Cache-Control"] = "no-store"
            elif html_response and (path in auth_ui_paths or bool(session.get("user"))):
                # Session-driven pages should never be publicly cached.
                response.headers["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
                response.headers["Pragma"] = "no-cache"
            else:
                response.headers.setdefault("Cache-Control", "public, max-age=60")
        except Exception:
            pass
        # ETag support for cacheable HTML responses
        try:
            if (
                response.status_code == 200
                and response.content_type
                and "text/html" in response.content_type
                and response.direct_passthrough is False
                and "no-store" not in (response.headers.get("Cache-Control", "").lower())
            ):
                data = response.get_data()
                etag = f'W/"{hashlib.md5(data).hexdigest()}"'
                response.headers["ETag"] = etag
                if request.headers.get("If-None-Match") == etag:
                    response.status_code = 304
                    response.set_data(b"")
        except Exception:
            pass
        # Baseline security headers for all responses.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if env == "production":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response

    if not SECRET_KEY or SECRET_KEY == "dev-insecure-change-me":
        logger.error("SECRET_KEY must be set via environment. Aborting.")
        raise SystemExit(1)

    try:
        with app.app_context():
            init_db()
    except Exception as exc:
        logger.warning("init_db failed: %s", exc)
        require_db = env == "production" or os.getenv("REQUIRE_DB_ON_STARTUP", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if require_db:
            logger.error("Database init is required; aborting startup.")
            raise SystemExit(1)

    @app.errorhandler(404)
    def handle_not_found(_error):
        if _api_request():
            return _api_error("not_found", "Resource not found", 404)
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(500)
    def handle_server_error(error):
        logger.exception("Unhandled error", exc_info=error)
        if _api_request():
            return _api_error("internal_error", "Internal server error", 500)
        return jsonify({"error": "internal error"}), 500

    @app.errorhandler(413)
    def handle_payload_too_large(_error):
        if _api_request():
            return _api_error("payload_too_large", "Payload too large", 413)
        return jsonify({"error": "payload_too_large"}), 413

    @app.errorhandler(429)
    def handle_rate_limited(_error):
        if _api_request():
            return _api_error("rate_limited", "Too many requests", 429)
        flash("Too many requests. Please wait and try again.", "error")
        return redirect(url_for("index"))

    def safe_parse_search_params(raw_title: str, raw_country: str) -> Tuple[str, str, Optional[int], Optional[int]]:
        """Safely parse and normalize search parameters."""
        try:
            cleaned_title, sal_floor, sal_ceiling = parse_salary_query(raw_title or "")
            title_q = normalize_title(cleaned_title)
            country_q = normalize_country(raw_country or "")
            return title_q, country_q, sal_floor, sal_ceiling
        except Exception as e:
            logger.warning(f"Search parameter parsing failed: {e}")
            return "", "", None, None

    @app.template_filter("slugify")
    def _slugify_filter(text: str) -> str:
        return _slugify(text or "")

    def _job_url(j, _external: bool = False) -> str:
        """Return canonical slug URL for a job dict used in templates."""
        jid = j.get("id", "") if isinstance(j, dict) else getattr(j, "id", "")
        jtitle = (j.get("title") or j.get("job_title") or "") if isinstance(j, dict) else getattr(j, "title", "")
        slug = _slugify(str(jtitle))
        canonical_id = f"{jid}-{slug}" if slug else str(jid)
        return url_for("job_detail", job_id=canonical_id, _external=_external)

    app.jinja_env.globals["job_url"] = _job_url

    @app.template_filter("datetime")
    def _jinja_datetime_filter(value):
        """Parse strings into datetime objects for templates when possible."""
        dt = _coerce_datetime(value)
        return dt or value

    @app.template_filter("timeago")
    def _jinja_timeago_filter(value):
        """Return a human readable relative time like '3 days ago'."""
        dt = _coerce_datetime(value)
        if not isinstance(dt, datetime):
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = now - dt
        seconds = max(0, int(diff.total_seconds()))

        def _fmt(amount: int, unit: str) -> str:
            suffix = "" if amount == 1 else "s"
            return f"{amount} {unit}{suffix} ago"

        if seconds < 60:
            return "just now"
        minutes = seconds // 60
        if minutes < 60:
            return _fmt(minutes, "minute")
        hours = minutes // 60
        if hours < 24:
            return _fmt(hours, "hour")
        days = hours // 24
        if days < 7:
            return _fmt(days, "day")
        weeks = days // 7
        if weeks < 5:
            return _fmt(weeks, "week")
        months = days // 30
        if months < 12:
            return _fmt(months, "month")
        years = max(1, days // 365)
        return _fmt(years, "year")

    @app.get("/")
    def index():
        """Render the main job search page with optional filters."""
        raw_title = (request.args.get("title") or "").strip()
        raw_country = (request.args.get("country") or "").strip()
        page, per_page = _resolve_pagination()
        per_page_display = _display_per_page(per_page)

        title_q, country_q, sal_floor, sal_ceiling = safe_parse_search_params(raw_title, raw_country)
        if raw_title and not title_q:
            title_q = normalize_title(raw_title)
        if raw_country and not country_q:
            country_q = normalize_country(raw_country)

        display_country = country_q or raw_country
        search_country = country_q

        if (
            sal_floor
            and sal_floor >= 100000
            and "100k" in raw_title.lower()
            and not raw_country
        ):
            search_country = "HIGH_PAY"
            display_country = "High-pay hubs"

        q_title = title_q or None
        q_country = search_country or None

        total = 0
        rows = []
        try:
            total = Job.count(q_title, q_country)
            offset = (max(1, page) - 1) * per_page
            rows = Job.search(q_title, q_country, limit=per_page, offset=offset)
        except Exception:
            logger.exception("Job lookup failed during index rendering")
            rows = []
            total = 0

        GUEST_JOB_LIMIT = 50
        guest_limit_hit = False
        if not session.get("user") and total > GUEST_JOB_LIMIT:
            total = GUEST_JOB_LIMIT
            offset_used = (max(1, page) - 1) * per_page
            rows = rows[:max(0, GUEST_JOB_LIMIT - offset_used)]
            guest_limit_hit = True

        items = []
        salary_cache = {}
        for row in rows:
            title = (row.get("job_title") or "(Untitled)").strip()
            title = re.sub(r"\s+", " ", title)
            job_date_raw = row.get("date")
            job_date_str = str(job_date_raw).strip() if job_date_raw is not None else ""
            link = row.get("link")
            if link in BLACKLIST_LINKS:
                link = None
            loc = row.get("location") or "Remote / Anywhere"
            median = None
            currency = None
            if loc in salary_cache:
                cached = salary_cache[loc]
                median, currency = cached[0], cached[1]
            else:
                try:
                    rec = get_salary_for_location(loc)
                    if rec:
                        median, currency = rec[0], rec[1]
                    else:
                        median, currency = None, None
                except Exception:
                    median, currency = None, None
                salary_cache[loc] = (median, currency)

            range_compact = None
            median_compact = None
            estimated_display = None
            uplift_factor = 1.0
            if median is not None:
                try:
                    from .models import db as _db_helpers
                    title_lc = title.lower()
                    if any(k in title_lc for k in TITLE_BUCKET2_KEYWORDS):
                        uplift_factor = 1.10
                    elif any(k in title_lc for k in TITLE_BUCKET1_KEYWORDS):
                        uplift_factor = 1.05

                    base_rng = _db_helpers.salary_range_around(float(median), pct=0.2)
                    if base_rng:
                        base_low, base_high, base_low_s, base_high_s = base_rng
                        base_median_compact = _db_helpers._compact_salary_number(float(median))

                        if uplift_factor > 1.0:
                            uplift_amount = float(median) * (uplift_factor - 1.0)
                            adj_low = base_low + uplift_amount
                            adj_high = base_high + uplift_amount
                            low_s = _db_helpers._compact_salary_number(adj_low)
                            high_s = _db_helpers._compact_salary_number(adj_high)
                            range_compact = (int(adj_low), int(adj_high))
                            estimated_display = f"{low_s}\u2013{high_s}"
                        else:
                            range_compact = (base_low, base_high)
                            estimated_display = f"{base_low_s}\u2013{base_high_s}"

                        median_compact = base_median_compact
                except Exception:
                    range_compact = None

            item_payload = {
                "id": row.get("id"),
                "title": title,
                "company": row.get("company_name") or "",
                "location": loc,
                "description": parse_job_description(row.get("job_description") or ""),
                "date_posted": format_job_date_string(job_date_str) if job_date_str else "",
                "date_raw": job_date_str,
                "link": link,
                "is_new": _job_is_new(job_date_raw, row.get("date")),
                "is_ghost": _job_is_ghost(job_date_raw),
                "median_salary": int(median) if median is not None else None,
                "median_salary_currency": currency,
                "median_salary_compact": median_compact,
                "estimated_salary_range_compact": estimated_display,
                "estimated_salary_range_numeric": range_compact,
                "salary_uplift_factor": uplift_factor if uplift_factor and uplift_factor > 1.0 else None,
            }

            match_score, match_reasons = _compute_match_score(
                job_title=title,
                job_location=loc,
                query_title=title_q,
                query_country=search_country or "",
                has_salary=bool(estimated_display or median),
                has_apply_link=bool(link),
            )
            item_payload["match_score"] = match_score
            item_payload["match_reasons"] = match_reasons

            # If a salary floor is present (e.g., >100k filter), drop jobs whose estimated top end is below the floor.
            if sal_floor and sal_floor >= 100000:
                est_high = range_compact[1] if range_compact else None
                med_val = median
                basis = est_high if est_high is not None else med_val
                if basis is None or basis < sal_floor:
                    continue

            items.append(item_payload)

        if not raw_title and not raw_country and not items:
            demo_jobs = _get_demo_jobs()
            items = demo_jobs
            total = len(demo_jobs)
            page = 1
            per_page = len(demo_jobs)
            per_page_display = _display_per_page(per_page)

        per_page_display = _display_per_page(per_page)
        pages_display = max(1, (total + per_page_display - 1) // per_page_display) if total else 1

        pagination = {
            "page": page,
            "pages": pages_display,
            "total": total,
            "per_page": per_page_display,
            "has_prev": page > 1,
            "has_next": page < pages_display,
            "prev_url": url_for("index", title=title_q or None, country=(raw_country or None), page=page - 1)
            if page > 1
            else None,
            "next_url": url_for("index", title=title_q or None, country=(raw_country or None), page=page + 1)
            if page < pages_display
            else None,
        }

        display_country = display_country or ""
        salary_band = _salary_band_label(sal_floor, sal_ceiling)

        cat_ctx = _get_category_context(title_q, display_country) if (title_q or display_country) else None

        remote_count = 0
        if not title_q and not display_country:
            try:
                remote_count = Job.count(None, "remote") or 0
            except Exception:
                remote_count = 0

        return render_template(
            "index.html",
            results=items,
            count=total,
            title_q=title_q,
            country_q=display_country,
            salary_band=salary_band,
            pagination=pagination,
            cat_ctx=cat_ctx,
            remote_count=remote_count,
            guest_limit_hit=guest_limit_hit,
        )

    @app.get("/remote")
    def remote_jobs():
        """301 redirect to remote jobs filter — preserves SEO equity for /remote URL."""
        return redirect(url_for("index", country="Remote"), 301)

    @app.get("/recruiter-salary-board")
    def recruiter_salary_board():
        """Surface the dedicated job browser experience."""
        job_api_url = url_for("api_jobs")
        return render_template(
            "job_browser.html",
            job_api=job_api_url,
        )

    def _query_jobs_payload(*, raw_title: str, raw_country: str, page: int, per_page: int) -> Dict[str, Any]:
        """Shared jobs listing payload for /api/jobs and /v1/jobs."""
        per_page_display = _display_per_page(per_page)

        title_q, country_q, _, _ = safe_parse_search_params(raw_title, raw_country)
        if raw_title and not title_q:
            title_q = normalize_title(raw_title)
        if raw_country and not country_q:
            country_q = normalize_country(raw_country)

        q_title = title_q or None
        q_country = country_q or None

        total: Optional[int]
        rows: List[Dict[str, Any]] = []
        try:
            total = Job.count(q_title, q_country)
        except Exception:
            logger.exception("Job COUNT failed; falling back to search-only")
            total = None

        try:
            offset = (max(1, page) - 1) * per_page
            rows = Job.search(q_title, q_country, limit=per_page, offset=offset)
        except Exception:
            logger.exception("Job SEARCH failed")
            rows = []

        if not rows and (q_title or raw_title):
            try:
                offset = (max(1, page) - 1) * per_page
                rows = Job.search(None, q_country, limit=per_page, offset=offset)
                if total is None:
                    total = len(rows)
            except Exception:
                logger.exception("Fallback country-only search failed")

        if total is None:
            total = len(rows)

        # Cap results for unauthenticated requests
        _GUEST_API_LIMIT = 50
        if not session.get("user") and total > _GUEST_API_LIMIT:
            total = _GUEST_API_LIMIT
            _api_offset = (max(1, page) - 1) * per_page
            rows = rows[:max(0, _GUEST_API_LIMIT - _api_offset)]

        items: List[Dict[str, Any]] = []
        for row in rows:
            job_date_raw = row.get("date")
            link = row.get("link")
            if link in BLACKLIST_LINKS:
                link = None
            title = (row.get("job_title") or "").strip()
            company = (row.get("company_name") or "").strip()
            location = row.get("location") or "Remote / Anywhere"
            description = clean_job_description_text(row.get("job_description") or "")
            dt = _coerce_datetime(job_date_raw) if job_date_raw else None
            job_date_formatted = dt.date().isoformat() if dt else ""

            items.append(
                {
                    "id": row.get("id"),
                    "title": title,
                    "job_title": title,
                    "job_company_name": company,
                    "company": company,
                    "description": description,
                    "job_description": description,
                    "link": link or "",
                    "location": location,
                    "city": row.get("city") or "",
                    "country": row.get("country") or "",
                    "region": row.get("region") or "",
                    "job_date": job_date_formatted,
                    "date": row.get("date"),
                    "is_new": _job_is_new(job_date_raw, row.get("date")),
                    "is_ghost": _job_is_ghost(job_date_raw),
                    "job_salary_range": row.get("job_salary_range") or "",
                }
            )

        pages_display = max(1, (total + per_page_display - 1) // per_page_display) if per_page_display else 1
        return {
            "items": items,
            "meta": {
                "page": max(1, page),
                "per_page": per_page_display,
                "total": total,
                "pages": pages_display,
                "has_prev": page > 1,
                "has_next": page < pages_display,
            },
        }

    @app.get("/api/jobs")
    def api_jobs():
        """Return jobs as JSON with pagination metadata."""
        raw_title = parse_str_arg(request.args, "title", default="", max_len=120)
        raw_country = parse_str_arg(request.args, "country", default="", max_len=80)
        page, per_page = _resolve_pagination()
        payload = _query_jobs_payload(raw_title=raw_title, raw_country=raw_country, page=page, per_page=per_page)
        return _api_success(payload)

    @app.get("/api/jobs/summary")
    def api_jobs_summary():
        """Return summary statistics for jobs matching filters: count, median salary, remote share.

        Salary resolution order:
        - Prefer numeric job_salary from jobs table when available.
        - Fallback to parsing job_salary_range strings.
        - Finally, fallback to salary table via get_salary_for_location.
        """
        raw_title = parse_str_arg(request.args, "title", default="", max_len=120)
        raw_country = parse_str_arg(request.args, "country", default="", max_len=80)
        cache_key = f"summary:{raw_title.lower()}|{raw_country.lower()}"
        cached = summary_cache.get(cache_key)
        if cached is not None:
            return _api_success(cached)

        cleaned_title, _, _ = parse_salary_query(raw_title)
        country_q = normalize_country(raw_country)
        title_q = normalize_title(cleaned_title)

        try:
            total = Job.count(title_q or None, country_q or None)
        except Exception:
            total = 0

        # Get a sample of jobs for salary calculation (limit to reasonable size)
        max_samples = 1000
        try:
            rows = Job.search(title_q or None, country_q or None, limit=max_samples, offset=0)
        except Exception:
            rows = []

        # Collect salary values, preferring numeric job_salary and falling back to job_salary_range
        salary_values = []
        sample_locations = []

        for row in rows:
            # Prefer numeric job_salary if present
            job_salary_val = row.get("job_salary")
            if job_salary_val is not None:
                try:
                    salary_values.append(float(job_salary_val))
                except Exception:
                    pass
            else:
                # Fallback to parsing job_salary_range string
                salary_range_str = row.get("job_salary_range") or ""
                if salary_range_str:
                    parsed = parse_salary_range_string(salary_range_str)
                    if parsed is not None:
                        salary_values.append(parsed)

            # Collect sample locations for salary-table fallback
            location = row.get("location") or ""
            if location and location not in sample_locations:
                sample_locations.append(location)

        # Compute median/average from collected salary values, with a heuristic
        # to downscale cent-based values (e.g. 12_100_000 -> 121_000).
        median_salary = None
        currency = None

        if salary_values:
            sorted_vals = sorted(salary_values)
            n = len(sorted_vals)

            # Heuristic: if median is very large, try treating values as cents
            # and rescale by 1/100 when that produces a plausible annual salary.
            median_raw = sorted_vals[n // 2]
            if median_raw >= 1_000_000:
                scaled = [v / 100.0 for v in salary_values]
                scaled_sorted = sorted(scaled)
                scaled_median = scaled_sorted[n // 2]
                if 20_000 <= scaled_median <= 500_000:
                    sorted_vals = scaled_sorted
                    salary_values = scaled

            if n >= 3:
                if n % 2 == 0:
                    median_salary = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0
                else:
                    median_salary = float(sorted_vals[n // 2])
            else:
                median_salary = sum(sorted_vals) / n
            currency = "USD"
        else:
            # No direct salary values, try fallback to salary table
            fallback_salaries = []
            for loc in sample_locations[:5]:
                result = get_salary_for_location(loc)
                if result:
                    salary_val, curr = result
                    if salary_val:
                        fallback_salaries.append(salary_val)
                        if currency is None and curr:
                            currency = curr

            if fallback_salaries:
                median_salary = sum(fallback_salaries) / len(fallback_salaries)
                if currency is None:
                    currency = "USD"

        # Calculate remote share (simple heuristic: check if location contains "remote")
        remote_count = 0
        for row in rows:
            location = (row.get("location") or "").lower()
            if "remote" in location:
                remote_count += 1

        remote_share = remote_count / len(rows) if rows else 0.0

        payload = {
            "count": total,
            "salary": {
                "median": int(median_salary) if median_salary is not None else None,
                "currency": currency or None,
            },
            "remote_share": round(remote_share, 2),
        }
        summary_cache.set(cache_key, payload)
        return _api_success(payload)

    @app.post("/subscribe")
    @_limit("20 per minute")
    def subscribe():
        """Handle newsletter subscriptions from form or JSON payloads."""
        is_json = request.is_json
        payload = request.get_json(silent=True) or {} if is_json else request.form
        if not _csrf_valid():
            if is_json:
                return jsonify({"error": "invalid_csrf"}), 400
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("index"))
        email = (payload.get("email") or "").strip()
        job_id_raw = (payload.get("job_id") or "").strip()
        search_title = (payload.get("search_title") or "").strip()
        search_country = (payload.get("search_country") or "").strip()
        search_salary_band = (payload.get("search_salary_band") or "").strip()
        digest_label_parts = [p for p in [search_title, search_country, search_salary_band] if p]
        digest_label = " / ".join(digest_label_parts[:3])

        try:
            email = validate_email(email, check_deliverability=False).normalized
        except EmailNotValidError:
            if is_json:
                return jsonify({"error": "invalid_email"}), 400
            flash("Please enter a valid email.", "error")
            return redirect(url_for("index"))

        job_link = Job.get_link(job_id_raw)
        next_url = (payload.get("next") or "").strip()
        if not job_link and next_url and _is_safe_redirect_target(next_url):
            job_link = next_url
        status = insert_subscriber(email, search_title=search_title, search_country=search_country, search_salary_band=search_salary_band)

        if job_link:
            if status == "error":
                if is_json:
                    return jsonify({"error": "subscribe_failed"}), 500
                flash("We couldn't process your email. Please try again later.", "error")
                return redirect(url_for("index"))
            if is_json:
                body = {"status": status}
                if job_link:
                    body["redirect"] = job_link
                return jsonify(body), 200
            if status == "ok":
                flash("You're subscribed! You're all set.", "success")
            elif status == "duplicate":
                flash("You're already on the list.", "success")
            return redirect(job_link)

        if status == "ok":
            _send_subscribe_confirmation(email, digest_label)
            message = "You're subscribed to the weekly high-match digest."
            if digest_label:
                message = f"{message} Focus: {digest_label}."
            if is_json:
                body = {
                    "status": "ok",
                    "digest": {
                        "title": search_title,
                        "country": search_country,
                        "salary_band": search_salary_band,
                    },
                }
                if job_link:
                    body["redirect"] = job_link
                return jsonify(body), 200
            flash(message, "success")
        elif status == "duplicate":
            if is_json:
                body = {
                    "error": "duplicate",
                    "digest": {
                        "title": search_title,
                        "country": search_country,
                        "salary_band": search_salary_band,
                    },
                }
                if job_link:
                    body["redirect"] = job_link
                return jsonify(body), 200
            flash("You're already subscribed to the weekly digest.", "success")
        else:
            if is_json:
                return jsonify({"error": "subscribe_failed"}), 500
            flash("We couldn't process your email. Please try again later.", "error")
            return redirect(url_for("index"))

        if is_json:
            body = {"status": status or "ok"}
            if job_link:
                body["redirect"] = job_link
            return jsonify(body), 200
        return redirect(url_for("index"))

    @app.post("/subscribe.json")
    @_limit("20 per minute")
    def subscribe_json():
        """Alias JSON endpoint for compatibility."""
        return subscribe()

    @app.route("/register", methods=["GET", "POST"])
    @_limit("10 per minute")
    def register():
        if session.get("user"):
            return redirect(url_for("studio"))
        if request.method == "GET":
            return render_template("register.html", tab="signup", account_type="candidate")

        action = request.form.get("action", "signup")
        if action not in {"signup", "login"}:
            action = "login"
        email = (request.form.get("email") or "").strip()
        password = (request.form.get("password") or "").strip()
        account_type = _normalize_account_type(request.form.get("account_type", "candidate"))
        if not _csrf_valid():
            flash("Session expired. Please try again.", "error")
            return render_template("register.html", tab=action, account_type=account_type), 400
        try:
            email = validate_email(email, check_deliverability=False).normalized
        except Exception:
            flash("Please enter a valid email.", "error")
            return render_template("register.html", tab=action, account_type=account_type), 400

        sb = _get_supabase()
        if not sb:
            flash("Auth service unavailable.", "error")
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
            return redirect(url_for("studio"))
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

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        if request.method == "GET":
            return redirect(url_for("index"))
        if not _csrf_valid():
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("index"))
        session.pop("user", None)
        return redirect(url_for("index"))

    @app.post("/account/delete")
    @_limit("5 per hour")
    def account_delete():
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))
        if not _csrf_valid():
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("profile"))
        user_id = str(user.get("id") or "").strip()
        if not user_id:
            session.pop("user", None)
            flash("Please sign in again.", "error")
            return redirect(url_for("register"))
        delete_confirmation = (request.form.get("confirm_delete") or "").strip()
        if delete_confirmation != "DELETE":
            flash("Type DELETE to confirm account deletion.", "error")
            return redirect(url_for("profile"))
        err = _delete_auth_user(user_id)
        if err:
            flash(err, "error")
            return redirect(url_for("profile"))
        session.pop("user", None)
        flash("Your account has been deleted.", "success")
        return redirect(url_for("index"))

    @app.get("/studio")
    def studio():
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))
        return render_template("studio.html", user=user)

    @app.route("/profile", methods=["GET", "POST"])
    @_limit("10 per minute")
    def profile():
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))
        user_id = str(user.get("id") or "").strip()
        if not user_id:
            session.pop("user", None)
            flash("Please sign in again.", "error")
            return redirect(url_for("register"))
        if request.method == "GET":
            profile_data, err = _get_user_profile_metadata(user_id)
            if err and err != "Auth service unavailable.":
                flash(err, "error")
            return render_template("profile.html", user=user, profile=profile_data)
        if not _csrf_valid():
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("profile"))
        payload = {field: (request.form.get(field) or "").strip() for field in _PROFILE_FIELDS}
        err = _save_user_profile_metadata(user_id, payload)
        if err:
            flash(err, "error")
            return render_template("profile.html", user=user, profile=_clean_profile_data(payload)), 503 if "unavailable" in err.lower() else 400
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))

    @app.get("/hire")
    def hire():
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))
        user_id = str(user.get("id") or "").strip()
        if not user_id:
            session.pop("user", None)
            return redirect(url_for("register"))
        hire_data, err = _get_hire_metadata(user_id)
        if err and err != "Auth service unavailable.":
            flash(err, "error")
        account_type = hire_data.get("account_type", "candidate")
        hire_access = bool(hire_data.get("hire_access"))
        session["user"]["account_type"] = account_type
        session["user"]["hire_access"] = hire_access
        if not _is_hire_eligible(account_type, hire_access):
            flash("Complete your company setup to access Hire.", "error")
            return redirect(url_for("hire_onboarding"))
        return render_template("hire.html", user=user, hire=hire_data)

    @app.route("/hire/onboarding", methods=["GET", "POST"])
    @_limit("10 per minute")
    def hire_onboarding():
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))
        user_id = str(user.get("id") or "").strip()
        if not user_id:
            session.pop("user", None)
            return redirect(url_for("register"))
        if request.method == "GET":
            hire_data, err = _get_hire_metadata(user_id)
            if err and err != "Auth service unavailable.":
                flash(err, "error")
            return render_template("hire_onboarding.html", user=user, hire=hire_data)
        if not _csrf_valid():
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("hire_onboarding"))
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
        return redirect(url_for("hire"))

    @app.post("/contact")
    @_limit("12 per minute")
    def contact():
        """Handle contact form submissions (JSON or form)."""
        is_json = request.is_json
        payload = request.get_json(silent=True) or {} if is_json else request.form
        if not _csrf_valid():
            if is_json:
                return jsonify({"error": "invalid_csrf"}), 400
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("index"))
        email_raw = (payload.get("email") or "").strip()
        name_raw = (payload.get("name") or payload.get("name_company") or payload.get("company") or "").strip()
        message_raw = (payload.get("message") or "").strip()

        try:
            email = validate_email(email_raw, check_deliverability=False).normalized
        except EmailNotValidError:
            if is_json:
                return jsonify({"error": "invalid_email"}), 400
            flash("Please enter a valid email.", "error")
            return redirect(url_for("index"))

        if not name_raw or len(name_raw) < 2:
            if is_json:
                return jsonify({"error": "invalid_name"}), 400
            flash("Please add your name or company.", "error")
            return redirect(url_for("index"))

        if not message_raw or len(message_raw) < 5:
            if is_json:
                return jsonify({"error": "invalid_message"}), 400
            flash("Please add a short message.", "error")
            return redirect(url_for("index"))

        status = insert_contact(email=email, name_company=name_raw, message=message_raw)

        if status != "ok":
            if is_json:
                return jsonify({"error": "contact_failed"}), 500
            flash("We could not send your message. Please try again.", "error")
            return redirect(url_for("index"))

        if is_json:
            return jsonify({"status": "ok"}), 200
        flash("Thanks! We received your message.", "success")
        return redirect(url_for("index"))

    @app.post("/contact.json")
    @_limit("12 per minute")
    def contact_json():
        """Alias JSON endpoint for compatibility."""
        return contact()

    @app.post("/job-posting")
    @_limit("10 per minute")
    def job_posting():
        """Handle recruiter job posting submissions (JSON or form).

        Restricted to recruiter and company account types only.
        """
        is_json = request.is_json
        payload = request.get_json(silent=True) or {} if is_json else request.form

        # --- Auth: recruiter/company accounts only ---
        user = session.get("user")
        if not user:
            if is_json:
                return jsonify({"error": "auth_required"}), 401
            flash("Sign in to post a job.", "error")
            return redirect(url_for("register"))

        account_type = (user.get("account_type") or "").lower()
        if account_type not in ("recruiter", "company"):
            if is_json:
                return jsonify({"error": "recruiter_account_required"}), 403
            flash("Job posting is available for recruiter and company accounts only.", "error")
            return redirect(url_for("hire_onboarding"))

        # --- Plan check (Elite/Premium gate — integration pending) ---
        # Uncomment when payment tiers are live:
        # user_plan = (user.get("plan") or "free").lower()
        # if user_plan not in ("elite", "premium"):
        #     if is_json:
        #         return jsonify({"error": "plan_upgrade_required"}), 403
        #     flash("Upgrade to Elite or Premium to post jobs.", "error")
        #     return redirect(url_for("pricing"))

        user_id = str(user.get("id") or "").strip() or None

        if not _csrf_valid():
            if is_json:
                return jsonify({"error": "invalid_csrf"}), 400
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("index"))

        contact_email_raw = (payload.get("contact_email") or payload.get("email") or "").strip()
        job_title_raw = (payload.get("job_title") or "").strip()
        company_raw = (payload.get("company") or "").strip()
        description_raw = (payload.get("description") or "").strip()
        salary_range_raw = (payload.get("salary_range") or "").strip()

        try:
            contact_email = validate_email(contact_email_raw, check_deliverability=False).normalized
        except EmailNotValidError:
            if is_json:
                return jsonify({"error": "invalid_email"}), 400
            flash("Please enter a valid contact email.", "error")
            return redirect(url_for("index"))

        def _word_count(text: str) -> int:
            if not text:
                return 0
            return len(re.findall(r"\b\w+\b", text))

        if len(job_title_raw) < 2:
            if is_json:
                return jsonify({"error": "invalid_title"}), 400
            flash("Please add a job title.", "error")
            return redirect(url_for("index"))

        if len(company_raw) < 2:
            if is_json:
                return jsonify({"error": "invalid_company"}), 400
            flash("Please add a company name.", "error")
            return redirect(url_for("index"))

        if len(description_raw) < 10:
            if is_json:
                return jsonify({"error": "invalid_description"}), 400
            flash("Please add a short description.", "error")
            return redirect(url_for("index"))

        if _word_count(description_raw) > 5000:
            if is_json:
                return jsonify({"error": "description_too_long"}), 400
            flash("Description is too long (max ~5000 words).", "error")
            return redirect(url_for("index"))

        status = insert_job_posting(
            contact_email=contact_email,
            job_title=job_title_raw,
            company=company_raw,
            description=description_raw,
            salary_range=salary_range_raw,
            user_id=user_id,
        )

        if status != "ok":
            if is_json:
                return jsonify({"error": "job_posting_failed"}), 500
            flash("We could not submit the job. Please try again.", "error")
            return redirect(url_for("index"))

        if is_json:
            return jsonify({"status": "ok"}), 200
        flash("Thanks! Your job submission was received.", "success")
        return redirect(url_for("index"))

    @app.post("/job-posting.json")
    @_limit("10 per minute")
    def job_posting_json():
        """Alias JSON endpoint for compatibility."""
        return job_posting()

    @app.post("/events/apply")
    @_limit("120 per minute")
    def events_apply():
        """Record analytics events (apply/filter/etc.)."""
        payload = request.get_json(silent=True) or {}
        event_type = (payload.get("event_type") or "apply").strip().lower() or "apply"
        status = (payload.get("status") or "").strip()
        source = (payload.get("source") or "web").strip() or "web"
        email_hash = (payload.get("email_hash") or "").strip()
        meta_dict: Dict[str, str] = {}
        payload_meta = payload.get("meta")
        if isinstance(payload_meta, dict):
            for key, value in payload_meta.items():
                if key is None or value is None:
                    continue
                meta_dict[str(key)] = str(value)

        if event_type == "filter":
            filter_type = (payload.get("filter_type") or "").strip()
            filter_value = (payload.get("filter_value") or "").strip()
            raw_title = filter_type or "filter"
            raw_country = filter_value
            norm_title = filter_type.lower() if filter_type else ""
            norm_country = ""
            status = status or "selected"
            if filter_type:
                meta_dict["filter_type"] = filter_type
            if filter_value:
                meta_dict["filter_value"] = filter_value
            job_id = ""
            job_title = ""
            job_company = ""
            job_location = ""
            job_link = ""
            job_summary = ""
        else:
            job_id = (payload.get("job_id") or payload.get("jobId") or "").strip()
            job_title = (payload.get("job_title") or payload.get("jobTitle") or "").strip()
            job_company = (payload.get("job_company") or payload.get("jobCompany") or "").strip()
            job_location = (payload.get("job_location") or payload.get("jobLocation") or "").strip()
            job_link = (payload.get("job_link") or payload.get("jobLink") or "").strip()
            job_summary = (payload.get("job_summary") or payload.get("jobSummary") or "").strip()
            raw_title = job_title or "N/A"
            raw_country = job_location or "N/A"
            norm_title = ""
            norm_country = ""
            status = status or "unknown"
            if job_link:
                meta_dict.setdefault("job_link", job_link)

        return jsonify({"status": "ok"}), 200

    @app.get("/api/salary-insights")
    def api_salary_insights():
        """Return a lightweight public dataset of jobs for salary insights."""
        raw_title = parse_str_arg(request.args, "title", default="", max_len=120)
        raw_country = parse_str_arg(request.args, "country", default="", max_len=80)
        limit = parse_int_arg(request.args, "limit", default=100, minimum=1, maximum=300)
        cache_key = f"salary-insights:{raw_title.lower()}|{raw_country.lower()}|{limit}"
        cached = salary_insights_cache.get(cache_key)
        if cached is not None:
            return _api_success(cached)
        title_q = normalize_title(raw_title)
        country_q = normalize_country(raw_country)
        rows = Job.search(title_q or None, country_q or None, limit=limit, offset=0)
        items = [
            {
                "title": _to_lc(row.get("job_title") or ""),
                "location": row.get("location"),
                "job_date": format_job_date_string((row.get("date") or "").strip()),
                "link": row.get("link"),
                "is_new": _job_is_new(row.get("date"), row.get("date")),
            }
            for row in rows
        ]
        payload = {
            "count": len(items),
            "items": items,
            "meta": {"title": title_q, "country": country_q, "limit": limit},
        }
        salary_insights_cache.set(cache_key, payload)
        return _api_success(payload)

    @app.get("/api/autocomplete")
    @_limit("90 per minute")
    def api_autocomplete():
        """Return distinct job title suggestions for autocomplete."""
        q = parse_str_arg(request.args, "q", default="", max_len=80).lower()
        if len(q) < 2:
            return _api_success({"suggestions": []})
        cache_key = f"autocomplete:{q}"
        cached = autocomplete_cache.get(cache_key)
        if cached is not None:
            return _api_success(cached)
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT job_title FROM jobs "
                    "WHERE LOWER(job_title) LIKE %s "
                    "ORDER BY job_title LIMIT 8",
                    (f"%{q}%",),
                )
                rows = cur.fetchall()
                suggestions = [r[0] for r in rows if r[0]]
        except Exception:
            logger.exception("Autocomplete query failed")
            suggestions = []
        payload = {"suggestions": suggestions}
        autocomplete_cache.set(cache_key, payload)
        return _api_success(payload)

    @app.get("/api/share-search")
    @_limit("90 per minute")
    def api_share_search():
        """Return a canonical share payload for the current search filters."""
        title = parse_str_arg(request.args, "title", default="", max_len=120)
        country = parse_str_arg(request.args, "country", default="", max_len=80)
        page = parse_int_arg(request.args, "page", default=1, minimum=1, maximum=10_000)
        per_page = parse_int_arg(
            request.args,
            "per_page",
            default=12,
            minimum=1,
            maximum=int(app.config.get("PER_PAGE_MAX", 100)),
        )

        canonical_url = url_for(
            "index",
            title=title or None,
            country=country or None,
            page=page,
            per_page=per_page,
            _external=True,
        )
        return _api_success(
            {
                "canonical_url": canonical_url,
                "query": {
                    "title": title,
                    "country": country,
                    "page": page,
                    "per_page": per_page,
                },
            }
        )

    @app.get("/api/salary/compare")
    @_limit("90 per minute")
    def api_salary_compare():
        """Compare salary baselines between two regions/locations for a role."""
        role = parse_str_arg(request.args, "role", default="", max_len=120)
        region_a = parse_str_arg(request.args, "region_a", default="", max_len=120)
        region_b = parse_str_arg(request.args, "region_b", default="", max_len=120)
        if not region_a or not region_b:
            return _api_error(
                "invalid_params",
                "region_a and region_b are required",
                400,
                details={"required": ["region_a", "region_b"]},
            )

        sal_a = get_salary_for_location(region_a)
        sal_b = get_salary_for_location(region_b)
        median_a = int(sal_a[0]) if sal_a and sal_a[0] else None
        median_b = int(sal_b[0]) if sal_b and sal_b[0] else None
        if median_a is None and median_b is None:
            return _api_error(
                "no_salary_data",
                "No salary data found for requested regions",
                404,
                details={"region_a": region_a, "region_b": region_b},
            )

        delta = None
        delta_pct = None
        if median_a is not None and median_b is not None:
            delta = median_a - median_b
            if median_b != 0:
                delta_pct = round((delta / median_b) * 100.0, 2)

        return _api_success(
            {
                "role": normalize_title(role) if role else "",
                "region_a": {"name": region_a, "median": median_a, "currency": sal_a[1] if sal_a else None},
                "region_b": {"name": region_b, "median": median_b, "currency": sal_b[1] if sal_b else None},
                "delta": delta,
                "delta_pct": delta_pct,
            }
        )

    @app.post("/studio-contact")
    @_limit("10 per minute")
    def studio_contact():
        """Minimal B2B studio intake endpoint reusing contact storage."""
        if not _csrf_valid():
            return _api_error("invalid_csrf", "Session expired. Please refresh and try again.", 400)
        payload = request.get_json(silent=True) or request.form or {}
        email_raw = (payload.get("email") or "").strip()
        name_raw = (payload.get("name") or payload.get("company") or "").strip()
        priority = (payload.get("priority") or "").strip()
        message_raw = (payload.get("message") or "").strip()

        if not email_raw or not name_raw:
            return _api_error(
                "invalid_params",
                "email and name/company are required",
                400,
                details={"required": ["email", "name"]},
            )
        try:
            email = validate_email(email_raw, check_deliverability=False).normalized
        except EmailNotValidError:
            return _api_error("invalid_email", "Please provide a valid email", 400)

        tagged_message = (
            "[Studio enquiry]\n"
            f"Priority: {priority or 'unspecified'}\n"
            f"Path: {request.path}\n"
            f"Message: {message_raw or 'N/A'}"
        )
        status = insert_contact(email=email, name_company=name_raw, message=tagged_message)
        if status != "ok":
            return _api_error("contact_failed", "Unable to submit studio enquiry", 500)
        return _api_success({"status": "ok"}, 201, code="created", message="Studio enquiry submitted")

    # ------------------------------------------------------------------
    # Stripe B2C subscriptions (Market Intelligence + API Access)
    # ------------------------------------------------------------------
    _STRIPE_B2C_PRODUCTS = {
        "mi_premium": {
            "price_id": os.getenv("STRIPE_PRICE_MI_PREMIUM", ""),
            "product_line": "market_intelligence",
            "tier": "premium",
            "name": "Market Intelligence Premium",
            "price_display": "$9",
            "tagline": "Full reports, complete salary benchmarks, hiring trends.",
            "features": [
                "Unlimited report access",
                "Full job board access",
                "Complete salary benchmarks",
                "Hiring trend data",
            ],
            "badge": None,
        },
        "mi_pro": {
            "price_id": os.getenv("STRIPE_PRICE_MI_PRO", ""),
            "product_line": "market_intelligence",
            "tier": "pro",
            "name": "Market Intelligence Pro",
            "price_display": "$99",
            "tagline": "Everything in Premium plus personalised reports and exports.",
            "features": [
                "Everything in Premium",
                "Personalised market intelligence reports",
                "Data exports (CSV / JSON)",
                "Priority support",
            ],
            "badge": "Best Value",
        },
        "api_access": {
            "price_id": os.getenv("STRIPE_PRICE_API_ACCESS", ""),
            "product_line": "api_access",
            "tier": "api",
            "name": "API Access",
            "price_display": "$4.99",
            "tagline": "10 000 calls/month across all endpoints.",
            "features": [
                "10 000 API calls/month",
                "All endpoints (jobs, salary, trends)",
                "Salary and trend data",
                "Standard support",
            ],
            "badge": None,
        },
    }

    # Price-ID → product key lookup (used in webhook)
    _B2C_PRICE_TO_KEY: Dict[str, str] = {
        p["price_id"]: k for k, p in _STRIPE_B2C_PRODUCTS.items() if p["price_id"]
    }

    def _handle_b2c_subscription_event(sub_obj: Dict) -> None:
        """Sync a Stripe subscription object to user_subscriptions."""
        sub_id = sub_obj.get("id", "")
        metadata = sub_obj.get("metadata") or {}
        user_id = metadata.get("user_id", "")
        user_email = metadata.get("user_email", "")
        product_line = metadata.get("product_line", "")
        tier = metadata.get("tier", "")

        if not user_id or not product_line:
            logger.warning("_handle_b2c_subscription_event: missing metadata sub=%s", sub_id)
            return

        # Resolve tier from live price (handles plan changes mid-subscription)
        items = (sub_obj.get("items") or {}).get("data") or []
        price_id = items[0]["price"]["id"] if items else None
        if price_id and price_id in _B2C_PRICE_TO_KEY:
            matched = _STRIPE_B2C_PRODUCTS[_B2C_PRICE_TO_KEY[price_id]]
            tier = matched["tier"]
            product_line = matched["product_line"]

        _STATUS_MAP = {
            "active": "active", "trialing": "active",
            "past_due": "past_due", "unpaid": "past_due",
            "incomplete": "past_due", "canceled": "cancelled",
        }
        status = _STATUS_MAP.get(sub_obj.get("status", ""), "past_due")
        upsert_user_subscription(
            user_id=user_id,
            user_email=user_email,
            product_line=product_line,
            tier=tier,
            stripe_customer_id=sub_obj.get("customer"),
            stripe_subscription_id=sub_id,
            stripe_price_id=price_id,
            status=status,
            current_period_end=sub_obj.get("current_period_end"),
            cancel_at_period_end=bool(sub_obj.get("cancel_at_period_end")),
        )

        # Keep API key quota in sync with api_access subscription tier
        if product_line == "api_access" and user_email:
            new_limit = 10_000 if status == "active" else 500
            update_api_key_limit_by_email(user_email, new_limit)

    @app.get("/pricing")
    def pricing():
        """B2C pricing page for Market Intelligence and API Access."""
        user = session.get("user")
        subs: Dict = {}
        if user:
            subs = get_user_subscriptions(user.get("id", ""))
        return render_template(
            "pricing.html",
            user=user,
            products=_STRIPE_B2C_PRODUCTS,
            subs=subs,
        )

    @app.post("/stripe/subscribe")
    @_limit("10 per hour")
    def stripe_subscribe():
        """Start a Stripe Checkout Session for a B2C subscription."""
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))
        if not _csrf_valid():
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("pricing"))

        plan_key = (request.form.get("plan_key") or "").strip()
        product = _STRIPE_B2C_PRODUCTS.get(plan_key)
        if not product or not product["price_id"]:
            flash("Invalid plan selected.", "error")
            return redirect(url_for("pricing"))

        user_id = user.get("id", "")
        user_email = user.get("email", "")
        _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        base_url = os.getenv("BASE_URL", request.host_url.rstrip("/"))

        # If already subscribed to this product line — upgrade/downgrade in place
        subs = get_user_subscriptions(user_id)
        existing = subs.get(product["product_line"])
        if existing and existing.get("status") == "active" and existing.get("stripe_subscription_id"):
            try:
                sub = _stripe.Subscription.retrieve(existing["stripe_subscription_id"])
                item_id = sub["items"]["data"][0]["id"]
                _stripe.Subscription.modify(
                    existing["stripe_subscription_id"],
                    items=[{"id": item_id, "price": product["price_id"]}],
                    proration_behavior="create_prorations",
                )
                flash(f"Switched to {product['name']}. Changes apply immediately.", "success")
                return redirect(url_for("subscription_manage"))
            except Exception as exc:
                logger.error("stripe_subscribe: plan change failed %s", exc)
                flash("Could not change plan. Please contact support.", "error")
                return redirect(url_for("pricing"))

        try:
            checkout_session = _stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": product["price_id"], "quantity": 1}],
                customer_email=user_email,
                success_url=f"{base_url}/stripe/subscription/success?plan_key={plan_key}",
                cancel_url=f"{base_url}/pricing",
                metadata={
                    "user_id": user_id,
                    "user_email": user_email,
                    "plan_key": plan_key,
                    "product_line": product["product_line"],
                    "tier": product["tier"],
                    "checkout_type": "b2c_subscription",
                },
                subscription_data={
                    "metadata": {
                        "user_id": user_id,
                        "user_email": user_email,
                        "plan_key": plan_key,
                        "product_line": product["product_line"],
                        "tier": product["tier"],
                    }
                },
            )
            return redirect(checkout_session.url, 303)
        except Exception as exc:
            logger.error("stripe_subscribe: checkout creation failed %s", exc)
            flash("Could not start checkout. Please try again.", "error")
            return redirect(url_for("pricing"))

    @app.get("/stripe/subscription/success")
    def subscription_success():
        """Landing page after a successful B2C subscription checkout."""
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))
        plan_key = request.args.get("plan_key", "")
        product = _STRIPE_B2C_PRODUCTS.get(plan_key)
        return render_template("subscription_success.html", user=user, product=product)

    @app.get("/account/subscription")
    def subscription_manage():
        """Manage active B2C subscriptions."""
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))
        subs = get_user_subscriptions(user.get("id", ""))
        return render_template(
            "subscription_manage.html",
            user=user,
            subs=subs,
            products=_STRIPE_B2C_PRODUCTS,
        )

    @app.post("/account/subscription/cancel")
    @_limit("10 per hour")
    def subscription_cancel():
        """Cancel a B2C subscription at period end."""
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))
        if not _csrf_valid():
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("subscription_manage"))

        product_line = (request.form.get("product_line") or "").strip()
        subs = get_user_subscriptions(user.get("id", ""))
        sub = subs.get(product_line)
        if not sub or not sub.get("stripe_subscription_id"):
            flash("No active subscription found.", "error")
            return redirect(url_for("subscription_manage"))

        try:
            _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
            _stripe.Subscription.modify(
                sub["stripe_subscription_id"],
                cancel_at_period_end=True,
            )
            flash("Subscription cancelled. You'll keep access until the end of the billing period.", "success")
        except Exception as exc:
            logger.error("subscription_cancel: failed %s", exc)
            flash("Could not cancel subscription. Please contact support.", "error")

        return redirect(url_for("subscription_manage"))

    # ------------------------------------------------------------------
    # Stripe B2B job posting payments
    # ------------------------------------------------------------------
    _STRIPE_PRODUCTS = {
        "core_post": {
            "price_id": os.getenv("STRIPE_PRICE_CORE_POST", "price_1TDCQw51Ord3K6CEfC1cpZxl"),
            "name": "Core Post",
            "tagline": "Single job listing, active for 100 days.",
            "price_display": "$109",
            "mode": "payment",
            "slots": 1,
            "badge": None,
            "features": [
                "1 job listing",
                "Active for 100 days",
                "Standard placement",
                "Email confirmation",
            ],
        },
        "premium_post": {
            "price_id": os.getenv("STRIPE_PRICE_PREMIUM_POST", "price_1TDCRZ51Ord3K6CEKkMuzfhi"),
            "name": "Premium Post",
            "tagline": "Top placement for 100 days.",
            "price_display": "$219",
            "mode": "payment",
            "slots": 1,
            "badge": "Most Popular",
            "features": [
                "1 job listing",
                "Active for 100 days",
                "Top placement in search",
                "Featured badge on listing",
                "Email confirmation",
            ],
        },
        "elite_plan": {
            "price_id": os.getenv("STRIPE_PRICE_ELITE_PLAN", "price_1TDCSC51Ord3K6CERYTUJFiT"),
            "name": "Elite Plan",
            "tagline": "3 featured posts per month. Cancel anytime.",
            "price_display": "$379",
            "mode": "subscription",
            "slots": 3,
            "badge": "Best Value",
            "features": [
                "3 featured job posts/month",
                "Priority placement",
                "Cancel anytime",
                "Dedicated account support",
                "Email confirmation",
            ],
        },
    }

    @app.get("/post-a-job")
    def post_a_job():
        """B2B pricing page for companies to post jobs."""
        user = session.get("user")
        return render_template(
            "post_job_pricing.html",
            user=user,
            products=_STRIPE_PRODUCTS,
            stripe_key=os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
        )

    @app.post("/stripe/checkout")
    @_limit("10 per minute")
    def stripe_checkout():
        """Create a Stripe Checkout Session and redirect the user."""
        user = session.get("user")
        if not user:
            flash("Please sign in to purchase a job posting.", "error")
            return redirect(url_for("register"))
        if not _csrf_valid():
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("post_a_job"))
        if not _stripe:
            flash("Payment service unavailable. Please try again later.", "error")
            return redirect(url_for("post_a_job"))

        plan_key = (request.form.get("plan_key") or "").strip()
        product = _STRIPE_PRODUCTS.get(plan_key)
        if not product:
            flash("Invalid plan selected.", "error")
            return redirect(url_for("post_a_job"))

        _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        base_url = os.getenv("BASE_URL", request.host_url.rstrip("/"))
        user_email = user.get("email", "")
        user_id = user.get("id", "")

        try:
            params: Dict[str, Any] = {
                "mode": product["mode"],
                "line_items": [{"price": product["price_id"], "quantity": 1}],
                "customer_email": user_email,
                "success_url": f"{base_url}/stripe/success?session_id={{CHECKOUT_SESSION_ID}}",
                "cancel_url": f"{base_url}/stripe/cancel",
                "metadata": {
                    "user_id": user_id,
                    "user_email": user_email,
                    "plan_key": plan_key,
                    "plan_name": product["name"],
                },
            }
            if product["mode"] == "subscription":
                params["subscription_data"] = {"metadata": {"user_id": user_id, "plan_key": plan_key}}

            checkout_session = _stripe.checkout.Session.create(**params)
        except Exception as exc:
            logger.warning("stripe_checkout error: %s", exc)
            flash("Could not initiate payment. Please try again.", "error")
            return redirect(url_for("post_a_job"))

        insert_stripe_order(
            stripe_session_id=checkout_session.id,
            user_id=user_id,
            user_email=user_email,
            price_id=product["price_id"],
            plan_key=plan_key,
            plan_name=product["name"],
        )
        return redirect(checkout_session.url, 303)

    @app.get("/stripe/success")
    def stripe_success():
        """Landing page after successful Stripe Checkout."""
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))

        session_id = (request.args.get("session_id") or "").strip()
        if not session_id:
            flash("No payment session found.", "error")
            return redirect(url_for("post_a_job"))

        order = get_stripe_order(session_id)
        if not order or order.get("user_id") != user.get("id"):
            flash("Payment not found or does not belong to your account.", "error")
            return redirect(url_for("post_a_job"))

        product = _STRIPE_PRODUCTS.get(order.get("plan_key", ""))
        return render_template(
            "post_job_submit.html",
            user=user,
            order=order,
            product=product,
        )

    @app.post("/stripe/submit-job")
    @_limit("10 per minute")
    def stripe_submit_job():
        """Handle job details submission after a successful payment."""
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))
        if not _csrf_valid():
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("post_a_job"))

        session_id = (request.form.get("stripe_session_id") or "").strip()
        order = get_stripe_order(session_id) if session_id else None
        if not order or order.get("user_id") != user.get("id"):
            flash("Invalid or unauthorised payment session.", "error")
            return redirect(url_for("post_a_job"))

        if order.get("job_submitted_at"):
            flash("A job has already been submitted for this order.", "error")
            return redirect(url_for("hire"))

        job_title = (request.form.get("job_title") or "").strip()
        company = (request.form.get("company") or "").strip()
        location = (request.form.get("location") or "").strip()
        description = (request.form.get("description") or "").strip()
        salary_range = (request.form.get("salary_range") or "").strip()
        apply_url = (request.form.get("apply_url") or "").strip()

        if len(job_title) < 2:
            flash("Please enter a job title.", "error")
            return redirect(url_for("stripe_success", session_id=session_id))
        if len(company) < 2:
            flash("Please enter a company name.", "error")
            return redirect(url_for("stripe_success", session_id=session_id))
        if len(description) < 20:
            flash("Please add a job description (at least 20 characters).", "error")
            return redirect(url_for("stripe_success", session_id=session_id))

        description_full = description
        if apply_url:
            description_full += f"\n\nApply here: {apply_url}"
        if location:
            description_full = f"Location: {location}\n\n{description_full}"

        status = insert_job_posting(
            contact_email=order["user_email"],
            job_title=job_title,
            company=company,
            description=description_full,
            salary_range=salary_range or None,
        )
        if status != "ok":
            flash("Could not save your job. Please contact support.", "error")
            return redirect(url_for("stripe_success", session_id=session_id))

        mark_stripe_order_job_submitted(stripe_session_id=session_id)

        admin_email = os.getenv("ADMIN_EMAIL", "").strip()
        if admin_email:
            _send_mail(
                admin_email,
                f"[New Job Posting] {job_title} at {company} ({order['plan_name']})",
                (
                    f"Plan: {order['plan_name']}\n"
                    f"Paid by: {order['user_email']}\n"
                    f"Session: {session_id}\n\n"
                    f"Title: {job_title}\n"
                    f"Company: {company}\n"
                    f"Location: {location or 'Not specified'}\n"
                    f"Salary: {salary_range or 'Not specified'}\n"
                    f"Apply URL: {apply_url or 'Not specified'}\n\n"
                    f"Description:\n{description}"
                ),
            )
        _send_mail(
            order["user_email"],
            f"Job posting confirmed: {job_title} at {company}",
            (
                f"Hi,\n\nYour job posting has been received and will go live shortly.\n\n"
                f"Plan: {order['plan_name']}\n"
                f"Job title: {job_title}\n"
                f"Company: {company}\n\n"
                f"We'll review and publish it within 24 hours.\n\n"
                f"Thanks,\nThe Catalitium Team\nhttps://catalitium.com"
            ),
        )

        flash("Job submitted! It will go live within 24 hours. Check your email for confirmation.", "success")
        return redirect(url_for("hire"))

    @app.get("/stripe/cancel")
    def stripe_cancel():
        """Landing page when a user cancels Stripe Checkout."""
        user = session.get("user")
        return render_template("stripe_cancel.html", user=user)

    @app.post("/stripe/webhook")
    def stripe_webhook():
        """Handle incoming Stripe webhook events."""
        if not _stripe:
            return jsonify({"error": "stripe_unavailable"}), 503

        _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        payload = request.get_data()
        sig_header = request.headers.get("Stripe-Signature", "")

        try:
            event = _stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except _stripe.error.SignatureVerificationError:
            logger.warning("stripe_webhook: invalid signature")
            return jsonify({"error": "invalid_signature"}), 400
        except Exception as exc:
            logger.warning("stripe_webhook parse error: %s", exc)
            return jsonify({"error": "bad_payload"}), 400

        event_type = event.get("type", "")
        data_obj = event["data"]["object"]

        if event_type == "checkout.session.completed":
            cs_id = data_obj.get("id", "")
            customer_id = data_obj.get("customer") or None
            subscription_id = data_obj.get("subscription") or None
            mark_stripe_order_paid(
                stripe_session_id=cs_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
            )
            logger.info("stripe_webhook: order paid session=%s", cs_id)

        elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
            _handle_b2c_subscription_event(data_obj)
            logger.info("stripe_webhook: subscription synced sub=%s type=%s", data_obj.get("id"), event_type)

        elif event_type == "customer.subscription.deleted":
            sub_id = data_obj.get("id", "")
            existing = get_subscription_by_stripe_id(sub_id)
            if existing:
                upsert_user_subscription(
                    user_id=existing["user_id"],
                    user_email=existing["user_email"],
                    product_line=existing["product_line"],
                    tier=existing["tier"],
                    stripe_subscription_id=sub_id,
                    status="cancelled",
                )
            logger.info("stripe_webhook: subscription cancelled sub=%s", sub_id)

        elif event_type == "invoice.payment_succeeded":
            sub_id = data_obj.get("subscription")
            if sub_id:
                try:
                    _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
                    sub_obj = _stripe.Subscription.retrieve(sub_id)
                    _handle_b2c_subscription_event(sub_obj)
                except Exception as exc:
                    logger.warning("stripe_webhook: invoice.payment_succeeded retrieve failed %s", exc)

        elif event_type == "invoice.payment_failed":
            sub_id = data_obj.get("subscription")
            customer_id = data_obj.get("customer", "")
            if sub_id:
                existing = get_subscription_by_stripe_id(sub_id)
                if existing:
                    upsert_user_subscription(
                        user_id=existing["user_id"],
                        user_email=existing["user_email"],
                        product_line=existing["product_line"],
                        tier=existing["tier"],
                        stripe_subscription_id=sub_id,
                        status="past_due",
                    )
            logger.warning("stripe_webhook: payment failed customer=%s sub=%s", customer_id, sub_id)

        return jsonify({"status": "ok"}), 200

    @app.get("/health")
    def health():
        """Expose a readiness probe indicating the database is reachable."""
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        except Exception:
            return _api_error("db_unavailable", "Database connection failed", 503)
        return _api_success({"status": "ok", "db": "connected"})

    @app.get("/legal")
    def legal():
        """Display combined privacy policy and terms information."""
        return render_template("legal.html")

    @app.get("/robots.txt")
    def robots_txt():
        """Expose robots.txt with sitemap reference and crawl directives."""
        body = "\n".join(
            [
                "User-agent: *",
                "Allow: /",
                "Disallow: /api/",
                "Disallow: /health",
                "Disallow: /events/",
                "",
                "User-agent: AdsBot-Google",
                "Allow: /",
                "",
                "User-agent: Googlebot-Image",
                "Allow: /static/img/",
                "",
                f"Sitemap: {url_for('sitemap', _external=True)}",
            ]
        )
        resp = Response(body, mimetype="text/plain")
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.get("/sitemap.xml")
    def sitemap():
        """Generate a lightweight XML sitemap for primary surfaces."""
        import time as _time
        if _sitemap_cache["data"] and _time.time() - _sitemap_cache["ts"] < 3600:
            return _sitemap_cache["data"]
        today = datetime.utcnow().date().isoformat()
        urls = []
        most_recent_date: Optional[str] = None

        def _add(loc: str, priority: str = "0.5", lastmod: str = today, changefreq: str = "weekly"):
            if loc:
                urls.append({"loc": loc, "priority": priority, "lastmod": lastmod, "changefreq": changefreq})

        _add(url_for("index", _external=True), priority="1.0", changefreq="daily")
        _add(url_for("about", _external=True), priority="0.8", changefreq="monthly")
        _add(url_for("resources", _external=True), priority="0.9", changefreq="weekly")
        _add(url_for("market_research_index", _external=True), priority="0.9", changefreq="weekly")
        for _r in REPORTS:
            _add(url_for("market_research_report", slug=_r["slug"], _external=True), priority="0.85", changefreq="monthly")
        _add(url_for("recruiter_salary_board", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("legal", _external=True), priority="0.2", changefreq="yearly")

        filter_targets = [
            {"title": "ai"},
            {"title": "developer"},
            {"title": "remote"},
            {"title": "senior"},
            {"title": ">100k"},
            {"country": "EU"},
            {"country": "US"},
            {"country": "UK"},
            {"country": "CH"},
        ]
        for target in filter_targets:
            loc = url_for("index", title=target.get("title"), country=target.get("country"), _external=True)
            _add(loc, priority="0.7", changefreq="daily")

        # Add individual job pages (last 60 days, up to 500)
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute(
                    """SELECT id, date, job_title FROM jobs
                       WHERE date >= NOW() - INTERVAL '60 days'
                       ORDER BY date DESC LIMIT 500"""
                )
                for row in cur.fetchall():
                    jid, jdate = row[0], row[1]
                    jtitle = row[2] if len(row) > 2 else ""
                    slug = _slugify(jtitle or "")
                    canonical_id = f"{jid}-{slug}" if slug else str(jid)
                    jloc = url_for("job_detail", job_id=canonical_id, _external=True)
                    jmod = jdate.strftime("%Y-%m-%d") if hasattr(jdate, "strftime") else today
                    if most_recent_date is None:
                        most_recent_date = jmod
                    _add(jloc, priority="0.5", lastmod=jmod, changefreq="monthly")
        except Exception as exc:
            logger.debug("sitemap job entries failed: %s", exc)

        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]
        for url in urls:
            xml_lines.append("  <url>")
            xml_lines.append(f"    <loc>{url['loc']}</loc>")
            xml_lines.append(f"    <lastmod>{url['lastmod']}</lastmod>")
            xml_lines.append(f"    <changefreq>{url.get('changefreq', 'weekly')}</changefreq>")
            xml_lines.append(f"    <priority>{url['priority']}</priority>")
            xml_lines.append("  </url>")
        xml_lines.append("</urlset>")
        resp = Response("\n".join(xml_lines), mimetype="application/xml")
        resp.headers["Cache-Control"] = "public, max-age=3600"
        if most_recent_date:
            resp.headers["Last-Modified"] = most_recent_date
        _sitemap_cache["data"] = resp
        _sitemap_cache["ts"] = _time.time()
        return resp

    # ------------------------------------------------------------------
    # Individual job detail page
    # ------------------------------------------------------------------
    @app.get("/jobs/<path:job_id>")
    def job_detail(job_id: str):
        """Render a dedicated page for a single job listing."""
        # Extract numeric ID prefix (slug may follow after the first hyphen)
        m = re.match(r"^(\d+)", job_id)
        numeric_id = m.group(1) if m else job_id
        row = Job.get_by_id(numeric_id)
        if not row:
            return jsonify({"error": "not found"}), 404

        title = re.sub(r"\s+", " ", (row.get("job_title") or "(Untitled)").strip())
        # Redirect bare /jobs/<id> to canonical /jobs/<id>-<slug> (301 permanent)
        slug = _slugify(title)
        canonical_id = f"{numeric_id}-{slug}" if slug else numeric_id
        if job_id != canonical_id:
            return redirect(url_for("job_detail", job_id=canonical_id), 301)
        company = (row.get("company_name") or "").strip()
        loc = row.get("location") or "Remote / Anywhere"
        description = parse_job_description(row.get("job_description") or "")
        link = row.get("link")
        if link in BLACKLIST_LINKS:
            link = None
        date_raw = row.get("date")
        date_str = str(date_raw).strip() if date_raw is not None else ""
        date_posted = format_job_date_string(date_str) if date_str else ""
        is_new = _job_is_new(date_raw, date_raw)
        is_ghost = _job_is_ghost(date_raw)
        salary_range = row.get("job_salary_range") or ""

        median = None
        currency = None
        try:
            rec = get_salary_for_location(loc)
            if rec:
                median, currency = rec[0], rec[1]
        except Exception:
            pass

        estimated_display = None
        salary_min = salary_max = None
        if median is not None:
            try:
                from .models import db as _db_helpers
                title_lc = title.lower()
                uplift = 1.10 if any(k in title_lc for k in TITLE_BUCKET2_KEYWORDS) else (
                    1.05 if any(k in title_lc for k in TITLE_BUCKET1_KEYWORDS) else 1.0)
                base_rng = _db_helpers.salary_range_around(float(median), pct=0.2)
                if base_rng:
                    base_low, base_high, base_low_s, base_high_s = base_rng
                    if uplift > 1.0:
                        amt = float(median) * (uplift - 1.0)
                        low_s = _db_helpers._compact_salary_number(base_low + amt)
                        high_s = _db_helpers._compact_salary_number(base_high + amt)
                        estimated_display = f"{low_s}\u2013{high_s}"
                        salary_min, salary_max = int(base_low + amt), int(base_high + amt)
                    else:
                        estimated_display = f"{base_low_s}\u2013{base_high_s}"
                        salary_min, salary_max = base_low, base_high
            except Exception:
                pass

        # Related jobs: same first keyword, exclude self
        related = []
        try:
            first_word = normalize_title((title.split()[0] if title else ""))
            rel_rows = Job.search(first_word or None, None, limit=5, offset=0)
            for r in rel_rows:
                if str(r.get("id")) != str(numeric_id) and len(related) < 3:
                    rd = r.get("date")
                    related.append({
                        "id": r.get("id"),
                        "title": (r.get("job_title") or "").strip(),
                        "company": (r.get("company_name") or "").strip(),
                        "location": r.get("location") or "Remote",
                        "date": format_job_date_string(str(rd).strip()) if rd else "",
                    })
        except Exception:
            pass

        job = {
            "id": canonical_id,
            "title": title,
            "company": company,
            "location": loc,
            "description": description,
            "date_posted": date_posted,
            "date_raw": date_str,
            "link": link,
            "is_new": is_new,
            "is_ghost": is_ghost,
            "salary_range": salary_range,
            "estimated_salary_range_compact": estimated_display,
            "median_salary_currency": currency,
            "salary_min": salary_min,
            "salary_max": salary_max,
        }
        detail_salary_band = ""
        if salary_min and salary_max:
            detail_salary_band = f"{int(salary_min/1000)}k-{int(salary_max/1000)}k"
        elif salary_range:
            detail_salary_band = str(salary_range).strip()[:48]
        # Fetch cached AI summary for server-side rendering (crawlable by Google)
        try:
            pk = int(str(numeric_id).strip())
            ai_summary = get_job_summary(pk)
        except Exception:
            ai_summary = None

        return render_template(
            "job_detail.html",
            job=job,
            related=related,
            ai_summary=ai_summary,
            subscribe_ctx={
                "title": title,
                "country": loc,
                "salary_band": detail_salary_band,
            },
        )

    # Salary tool removed — redirect old URLs to salary board
    @app.get("/salary-tool")
    @app.get("/salary-report")
    def salary_report():
        return redirect(url_for("recruiter_salary_board"), 301)

    # ------------------------------------------------------------------
    # Service worker (must be served from root scope)
    # ------------------------------------------------------------------
    @app.get("/sw.js")
    def service_worker():
        """Serve the PWA service worker from root so it controls all pages."""
        resp = send_from_directory(
            os.path.join(os.path.dirname(__file__), "static", "js"),
            "sw.js",
            mimetype="application/javascript",
        )
        resp.headers["Service-Worker-Allowed"] = "/"
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    # ------------------------------------------------------------------
    # About page
    # ------------------------------------------------------------------
    @app.get("/about")
    def about():
        """Render the About Catalitium page."""
        return render_template("about.html")

    @app.get("/companies")
    def companies():
        """Render the Companies spotlight page."""
        return render_template("companies.html")

    # ------------------------------------------------------------------
    # Resources hub — 301 redirect to Market Research
    # ------------------------------------------------------------------
    @app.get("/resources")
    def resources():
        """Redirect legacy /resources to the unified Market Research hub."""
        return redirect(url_for("market_research_index"), 301)

    # ------------------------------------------------------------------
    # Market Research hub + individual report pages
    # ------------------------------------------------------------------
    @app.get("/market-research")
    def market_research_index():
        """Market Research hub — lists all published reports."""
        user = session.get("user")
        mi_tier = _get_mi_tier(user)
        return render_template("market_research_index.html", reports=REPORTS, mi_tier=mi_tier)

    @app.get("/developers")
    def developers():
        """Simple, human-facing overview of the v1 JSON API."""
        return render_template(
            "developers.html",
        )

    @app.get("/market-research/<slug>")
    def market_research_report(slug):
        """Individual report landing page (fully SSR'd for SEO)."""
        report = next((r for r in REPORTS if r["slug"] == slug), None)
        if not report:
            abort(404)
        user = session.get("user")
        mi_tier = _get_mi_tier(user)
        return render_template(
            report.get("template", "reports/report.html"),
            report=report,
            mi_tier=mi_tier,
            user=user,
        )

    # ------------------------------------------------------------------
    # API Key lifecycle — register, confirm, usage, revoke
    # ------------------------------------------------------------------

    @app.post("/api/keys/register")
    @_limit("3 per hour")
    def api_keys_register():
        """Register a new API key; sends a confirmation email to the provided address."""
        data = request.get_json(silent=True) or {}
        raw_email = (data.get("email") or "").strip()
        if not raw_email:
            return jsonify({"error": "email_required"}), 400
        try:
            valid = validate_email(raw_email, check_deliverability=False)
            email = valid.normalized
        except EmailNotValidError as exc:
            return jsonify({"error": "invalid_email", "detail": str(exc)}), 400

        existing = get_api_key_by_email(email)
        if existing:
            if existing.get("is_active"):
                return jsonify({"message": "A key for this email already exists. Check your inbox for the original activation email."}), 200
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
        )
        if not ok:
            return jsonify({"error": "registration_failed"}), 500

        base_url = request.host_url.rstrip("/")
        confirm_url = f"{base_url}/api/keys/confirm?token={confirm_token}"
        body = (
            f"Hello,\n\n"
            f"Your Catalitium API key is:\n\n"
            f"  {raw_key}\n\n"
            f"To activate it, visit the link below (valid 24 hours):\n\n"
            f"  {confirm_url}\n\n"
            f"Once activated, include it in API requests with the header:\n"
            f"  X-API-Key: {raw_key}\n\n"
            f"Free tier: 100 requests/month.\n\n"
            f"-- Catalitium Team"
        )
        _send_mail(email, "Activate your Catalitium API key", body)
        logger.info("API key created prefix=%s ip=%s email=%s", key_prefix, ip, email)
        return jsonify({"message": "Check your email to activate your key."}), 200

    @app.get("/api/keys/confirm")
    def api_keys_confirm():
        """Activate an API key using the token from the confirmation email."""
        token = (request.args.get("token") or "").strip()
        if not token:
            return jsonify({"error": "token_required"}), 400
        ok = confirm_api_key_by_token(token, datetime.now(timezone.utc))
        if not ok:
            return jsonify({"error": "invalid_or_expired_token"}), 400
        return jsonify({"message": "Key activated. Your API key was included in the confirmation email you received."}), 200

    @app.get("/api/keys/usage")
    @_require_api_key
    def api_keys_usage():
        """Return monthly usage stats for the authenticated API key."""
        rec = g.get("api_key_record", {})
        now = datetime.now(timezone.utc)
        if now.month == 12:
            reset_dt = now.replace(year=now.year + 1, month=1, day=1,
                                   hour=0, minute=0, second=0, microsecond=0)
        else:
            reset_dt = now.replace(month=now.month + 1, day=1,
                                   hour=0, minute=0, second=0, microsecond=0)
        return jsonify({
            "tier": rec.get("tier"),
            "monthly_limit": rec.get("monthly_limit"),
            "requests_used": rec.get("requests_this_month"),
            "reset_date": reset_dt.date().isoformat(),
        }), 200

    @app.delete("/api/keys/me")
    def api_keys_revoke():
        """Revoke the API key supplied in X-API-Key (does not consume quota)."""
        raw_key = (
            request.headers.get("X-API-Key")
            or request.args.get("api_key")
            or ""
        ).strip()
        if not raw_key:
            return jsonify({"error": "invalid_key"}), 401
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        ok = revoke_api_key(key_hash)
        if not ok:
            return jsonify({"error": "invalid_key"}), 401
        return jsonify({"message": "Key revoked."}), 200

    # ------------------------------------------------------------------
    # v1/ — Authenticated data API (protected by _require_api_key)
    # ------------------------------------------------------------------

    @app.get("/v1/jobs")
    @_require_api_key
    def v1_jobs():
        """Authenticated job search; same parameters as /api/jobs."""
        raw_title = (request.args.get("title") or "").strip()
        raw_country = (request.args.get("country") or "").strip()
        page, per_page = _resolve_pagination()
        title_q, country_q, _, _ = safe_parse_search_params(raw_title, raw_country)
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
                dt = _coerce_datetime(date_raw)
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
                "is_new": _job_is_new(date_raw, date_raw),
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

    @app.get("/v1/jobs/<int:job_id>")
    @_require_api_key
    def v1_job_detail(job_id: int):
        """Return a single job as JSON."""
        row = Job.get_by_id(str(job_id))
        if not row:
            return jsonify({"error": "not_found"}), 404
        link = row.get("link")
        if link in BLACKLIST_LINKS:
            link = None
        date_raw = row.get("date")
        date_str = ""
        if date_raw:
            dt = _coerce_datetime(date_raw)
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
            "is_new": _job_is_new(date_raw, date_raw),
        }), 200

    @app.get("/v1/salary")
    @_require_api_key
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
            return jsonify({"error": "no_data"}), 404
        median, currency = rec[0], rec[1]
        return jsonify({
            "location": location,
            "median_salary": median,
            "currency": currency,
        }), 200

    # ------------------------------------------------------------------
    # AI Job Summary API (Claude Haiku, DB-cached)
    # ------------------------------------------------------------------
    @app.get("/api/summary/<int:job_id>")
    def api_summary(job_id: int):
        """Return AI-generated bullets + skill tags for a job (cached in DB)."""
        empty_summary = {"bullets": [], "skills": []}
        cached = get_job_summary(job_id)
        if cached:
            return _api_success(cached)

        row = Job.get_by_id(str(job_id))
        if not row:
            return _api_error("not_found", "Job not found", 404)

        description = (row.get("job_description") or "").strip()
        if len(description) < 50:
            return _api_success(empty_summary, code="summary_unavailable", message="description_too_short")

        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            return _api_success(empty_summary, code="summary_unavailable", message="provider_not_configured")

        bullets, skills = _call_anthropic(description, api_key)
        if bullets is None:
            return _api_success(empty_summary, code="summary_unavailable", message="provider_request_failed")

        try:
            save_job_summary(job_id, bullets, skills)
        except Exception:
            pass

        return _api_success({"bullets": bullets, "skills": skills})

    return app


def _job_is_new(job_date_raw, row_date) -> bool:
    """Return True when the job was posted within the last 7 days."""
    dt = _coerce_datetime(row_date) or _coerce_datetime(job_date_raw)
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return (now - dt) <= timedelta(days=7)


def _job_is_ghost(job_date_raw) -> bool:
    """Return True when the job was posted more than 30 days ago (may be filled)."""
    dt = _coerce_datetime(job_date_raw)
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt) > timedelta(days=30)


def _coerce_datetime(value) -> Optional[datetime]:
    """Convert assorted datetime-like inputs into timezone-aware datetimes when possible."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_datetime"):
        try:
            return value.to_datetime()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            iso = value.isoformat()
            return datetime.fromisoformat(iso)
        except Exception:
            pass
    text = str(value).strip()
    if not text:
        return None
    # Attempt ISO parsing first
    try:
        return datetime.fromisoformat(text)
    except Exception:
        pass
    formats = ("%Y-%m-%d", "%Y.%m.%d", "%Y%m%d", "%Y/%m/%d")
    for fmt in formats:
        try:
            dt = datetime.strptime(text[: len(fmt)], fmt)
            return dt
        except Exception:
            continue
    return None


def _to_lc(value: str) -> str:
    """Return a lowercase camel-style version of a string for API responses."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", value or "") if p]
    if not parts:
        return value or ""
    head, *tail = parts
    return head.lower() + "".join(part.capitalize() for part in tail)


if __name__ == "__main__":
    application = create_app()
    debug_env = os.getenv("FLASK_DEBUG", "")
    debug = debug_env.lower() in {"1", "true", "yes", "on"}
    application.run(debug=debug)
