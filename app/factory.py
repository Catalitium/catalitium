"""Flask application factory and route definitions for Catalitium."""

import csv
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
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

from .config import (
    PER_PAGE_MAX,
    GHOST_JOB_DAYS,
    GUEST_DAILY_LIMIT,
    SUMMARY_CACHE_TTL,
    SUMMARY_CACHE_MAX,
    AUTOCOMPLETE_CACHE_TTL,
    AUTOCOMPLETE_CACHE_MAX,
    SALARY_INSIGHTS_CACHE_TTL,
    SALARY_INSIGHTS_CACHE_MAX,
    SITEMAP_CACHE_TTL,
    CARL_CHAT_MAX_TURNS,
    CARL_CHAT_MAX_MESSAGE_CHARS,
)

# region support — inlined from former app/support (pure helpers, no Flask)
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class EmailNotValidError(ValueError):
    """Raised when an email address fails basic format validation."""


def validate_email(email: str, *, check_deliverability: bool = False):  # noqa: ARG001
    """Lightweight format-only email validator. Returns an object with .normalized."""
    class _Result:
        normalized: str

    r = _Result()
    r.normalized = email.strip().lower()
    if not _EMAIL_RE.match(r.normalized):
        raise EmailNotValidError(f"Invalid email: {email!r}")
    return r


def _coerce_datetime(value):
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
    """Return True when the job was posted more than GHOST_JOB_DAYS ago (may be filled)."""
    dt = _coerce_datetime(job_date_raw)
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt) > timedelta(days=GHOST_JOB_DAYS)


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug (max 60 chars)."""
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:60]


def _to_lc(value: str) -> str:
    """Return a lowercase camel-style version of a string for API responses."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", value or "") if p]
    if not parts:
        return value or ""
    head, *tail = parts
    return head.lower() + "".join(part.capitalize() for part in tail)


coerce_datetime = _coerce_datetime
job_is_new = _job_is_new
job_is_ghost = _job_is_ghost
slugify = _slugify
to_lc = _to_lc

# endregion support

from .mailer import (
    send_subscribe_welcome,
    send_api_key_activation,
    send_api_access_key_provisioned,
    send_api_access_payment_confirmed,
    send_api_key_activation_reminder,
    send_job_posting_admin_notification,
    send_job_posting_confirmation,
)
from .normalization import normalize_country, normalize_title
from .subscriber_fields import sanitize_subscriber_search_fields
from .spam_guards import (
    disposable_email_domain,
    honeypot_triggered,
    prepare_contact_submission,
)
from .models.db import (
    SECRET_KEY,
    SUPABASE_URL,
    logger,
    close_db,
    init_db,
    get_db,
    get_salary_for_location,
    parse_salary_query,
    parse_salary_range_string,
    salary_range_around,
    _compact_salary_number,
    parse_job_description,
    format_job_date_string,
    clean_job_description_text,
    insert_subscriber,
    insert_contact,
    upsert_profile_cv_extract,
    insert_job_posting,
    insert_salary_submission,
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
    sync_api_key_quota_for_api_access,
)

from .models.money import (
    compute_compensation_confidence,
    confidence_color,
    source_label as compensation_source_label,
    compute_percentile,
    get_ppp_indices,
    compare_cities_salary,
    get_function_benchmarks,
    get_salary_trends,
)
from .models.catalog import (
    categorize_function,
    compute_quality_score,
    get_explore_data,
    get_remote_companies,
    get_function_distribution,
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
from werkzeug.middleware.proxy_fix import ProxyFix
from .api_utils import (
    TTLCache,
    api_fail,
    api_ok,
    generate_request_id,
    parse_int_arg,
    parse_str_arg,
)
from .integrations.cv_extract import (
    CVExtractionError,
    extract_cv_from_upload,
    normalize_cv_text,
)
from .integrations.carl_mock_analysis import (
    build_mock_analysis,
    carl_effective_user_message,
    generate_chat_reply,
    is_carl_message_grounded,
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
        "intro": "The US remains the highest-paying market for tech globally. Major hubs include the San Francisco Bay Area, New York, Seattle, Austin, and Boston, plus fully remote-first companies headquartered across the country.",
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
        "intro": "Data science roles bridge statistics, programming, and business intelligence. Demand is strong across all sectors (from fintech to e-commerce), with Python, SQL, and cloud data platforms (Snowflake, BigQuery, dbt) as the core stack.",
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

_DEMO_JOBS_CSV = Path(__file__).parent / "data" / "demo_jobs.csv"


def _get_demo_jobs():
    """Return demo jobs for empty search results, loaded from demo_jobs.csv."""
    jobs = []
    try:
        with open(_DEMO_JOBS_CSV, newline="", encoding="utf-8") as fh:
            for i, row in enumerate(csv.DictReader(fh), start=1):
                jobs.append({
                    "id": f"demo-{i}",
                    "title": row.get("title", ""),
                    "company": row.get("company", ""),
                    "location": row.get("location", ""),
                    "description": row.get("description", ""),
                    "date_posted": row.get("date_posted", ""),
                    "date_raw": "",
                    "link": "",
                    "is_new": False,
                    "is_ghost": False,
                    "match_score": None,
                    "match_reasons": [],
                    "median_salary": None,
                    "median_salary_currency": None,
                    "median_salary_compact": None,
                    "estimated_salary_range_compact": None,
                    "estimated_salary_range_numeric": None,
                    "salary_delta_pct": None,
                    "salary_uplift_factor": None,
                })
    except Exception as exc:
        logger.warning("_get_demo_jobs: could not load %s: %s", _DEMO_JOBS_CSV, exc)
    return jobs

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
        "slug": "aaas-tipping-point-saas-economics-2026",
        "title": "The AaaS Tipping Point: Why AI Agents Are Killing SaaS Economics in 2026",
        "short_title": "The AaaS Tipping Point Report 2026",
        "description": (
            "Whether Agents as a Service can capture 30%+ of enterprise software spend by 2028: "
            "Gartner, IDC, McKinsey, and workflow-level TCO evidence on agentic AI vs. seat-based SaaS. "
            "37 sources, April 2026."
        ),
        "published": "2026-03-01",
        "published_display": "March 2026",
        "pdf_path": "",
        "read_time": "22 min read",
        "gated": True,
        "template": "reports/aaas_tipping_point.html",
        "keywords": [
            "AaaS agents as a service 2026",
            "AI agents vs SaaS economics",
            "enterprise software spend agentic AI",
            "Gartner agentic AI enterprise applications",
            "SaaS TCO vs AI agents",
            "Automation Anywhere AI service agents",
            "LangGraph pricing per action",
            "Fortune 500 AI agents production 2026",
        ],
    },
    {
        "slug": "ai-skill-premium-index-2026",
        "title": "The AI Skill Premium Index 2026: Which AI Skills Command the Highest Salary Premiums",
        "short_title": "AI Skill Premium Index 2026",
        "description": (
            "Lightcast, Levels.fyi, Pave, and SignalFire data on AI vs SWE pay: ~28% posting premium, "
            "43% with 2+ AI skills, LLM and safety specializations, myths vs reality. February 2026."
        ),
        "published": "2026-02-15",
        "published_display": "February 2026",
        "pdf_path": "",
        "read_time": "18 min read",
        "gated": True,
        "template": "reports/ai_skill_premium_index_2026.html",
        "keywords": [
            "AI skill salary premium 2026",
            "LLM engineer compensation vs ML engineer",
            "Lightcast AI job postings premium",
            "Levels.fyi AI engineer salary 2025",
            "MLOps salary premium",
            "AI safety alignment salary growth",
            "tech compensation Big Tech AI vs SWE",
        ],
    },
    {
        "slug": "european-llm-build-vs-buy-2026",
        "title": "From Build to Buy: How the LLM Platform Era Is Rewriting Software Economics (Europe)",
        "short_title": "European LLM Build vs Buy Report 2026",
        "description": (
            "Europe enterprise LLM market ~$1.09B, 76% of AI now purchased vs built, EU AI Act compliance costs, "
            "API pricing tiers, and talent benchmarks. 20+ sources, February 2026."
        ),
        "published": "2026-02-01",
        "published_display": "February 2026",
        "pdf_path": "",
        "read_time": "24 min read",
        "gated": True,
        "template": "reports/european_llm_build_buy_2026.html",
        "keywords": [
            "Europe LLM market 2026",
            "build vs buy enterprise AI Europe",
            "EU AI Act compliance cost SME",
            "Menlo Ventures AI purchased vs built",
            "European SaaS LLM API economics",
            "AI engineer salary Europe Switzerland Spain",
            "LLM API pricing comparison 2025",
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
        "gated": True,
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
            "disrupting the $315 billion SaaS industry, with sourced data from a16z, Gartner, "
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


# Email functions live in app/mailer.py — imported at the top of this file.


_sitemap_cache: dict = {"data": None, "ts": 0.0}

# ---------------------------------------------------------------------------
# Guest daily job view limit  (threshold defined in app/config.py)
# ---------------------------------------------------------------------------


def _guest_daily_remaining() -> int:
    """Return remaining guest job views for today. -1 means unlimited (signed in or subscribed)."""
    if session.get("user") or session.get("subscribed"):
        return -1
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if session.get("_guest_date") != today:
        session["_guest_date"] = today
        session["_guest_seen"] = 0
        session.modified = True
    return max(0, GUEST_DAILY_LIMIT - int(session.get("_guest_seen") or 0))


def _guest_daily_consume(count: int) -> None:
    """Record that `count` jobs were shown to a guest today."""
    if session.get("user") or session.get("subscribed"):
        return
    session["_guest_seen"] = int(session.get("_guest_seen") or 0) + count
    session.modified = True


def safe_parse_search_params(raw_title: str, raw_country: str) -> Tuple[str, str, Optional[int], Optional[int]]:
    """Safely parse and normalize search parameters."""
    try:
        cleaned_title, sal_floor, sal_ceiling = parse_salary_query(raw_title or "")
        title_q = normalize_title(cleaned_title)
        country_q = normalize_country(raw_country or "")
        return title_q, country_q, sal_floor, sal_ceiling
    except Exception as e:
        logger.debug("Search parameter parsing failed: %s", e)
        return "", "", None, None


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
        # Default 5MB so CV uploads match ``cv_extract`` (4MB) without extra .env tuning.
        MAX_CONTENT_LENGTH=int(os.getenv("MAX_CONTENT_LENGTH", str(5 * 1024 * 1024))),
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
        # Skip compressing tiny responses (library default 500; slightly higher = less CPU on small HTML/JSON)
        app.config.setdefault("COMPRESS_MIN_SIZE", 1024)
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

    # Store limiter so blueprint helpers can access it via current_app.extensions
    if limiter is not None:
        app.extensions["limiter"] = limiter

    # Register route blueprints (extracted from this file for readability)
    from .controllers import ALL_BLUEPRINTS
    for _bp in ALL_BLUEPRINTS:
        app.register_blueprint(_bp)

    def _exempt_public_jobs(fn):
        """Do not apply default rate limits to public GET /jobs (SEO + search UX)."""
        if limiter is None:
            return fn
        return limiter.exempt(fn)

    summary_cache = TTLCache(ttl_seconds=SUMMARY_CACHE_TTL, max_size=SUMMARY_CACHE_MAX)
    autocomplete_cache = TTLCache(ttl_seconds=AUTOCOMPLETE_CACHE_TTL, max_size=AUTOCOMPLETE_CACHE_MAX)
    salary_insights_cache = TTLCache(ttl_seconds=SALARY_INSIGHTS_CACHE_TTL, max_size=SALARY_INSIGHTS_CACHE_MAX)

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
        """Decorator: validate X-API-Key header, enforce daily quota, inject rate-limit headers."""
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
                return jsonify({
                    "error": "quota_exceeded",
                    "window": usage.get("window", "daily"),
                }), 429
            g.api_key_record = usage

            @after_this_request
            def _inject_ratelimit_headers(response):
                rec = g.get("api_key_record", {})
                limit = rec.get("daily_limit", 50)
                used = rec.get("requests_today", 0)
                _now = datetime.now(timezone.utc)
                reset_dt = (_now + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                response.headers["X-RateLimit-Limit"] = str(limit)
                response.headers["X-RateLimit-Remaining"] = str(max(0, limit - used))
                response.headers["X-RateLimit-Reset"] = reset_dt.isoformat()
                response.headers["X-RateLimit-Window"] = "daily"
                return response

            return f(*args, **kwargs)
        return decorated

    def _apply_cache_control_headers(response: Response) -> None:
        """Set Cache-Control by response type: static (long), API (no-store), auth HTML (private), else short public."""
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
            response.headers.setdefault("Cache-Control", "public, max-age=2592000, immutable")
        elif path.startswith("/api/") or path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
        elif html_response and (path in auth_ui_paths or bool(session.get("user"))):
            response.headers["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        else:
            response.headers.setdefault("Cache-Control", "public, max-age=60")

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
        try:
            _apply_cache_control_headers(response)
        except Exception:
            pass
        # ETag for small HTML only; hashing large pages on every request burns CPU (slow TTFB).
        try:
            if (
                response.status_code == 200
                and response.content_type
                and "text/html" in response.content_type
                and response.direct_passthrough is False
                and "no-store" not in (response.headers.get("Cache-Control", "").lower())
            ):
                data = response.get_data()
                if len(data) <= 65536:
                    etag = f'W/"{hashlib.md5(data).hexdigest()}"'
                    response.headers["ETag"] = etag
                    if request.headers.get("If-None-Match") == etag:
                        response.status_code = 304
                        response.set_data(b"")
        except Exception:
            pass
        # Baseline security headers for all responses.
        response.headers.setdefault(
            "X-Request-ID", str(getattr(g, "request_id", "") or "")
        )
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

    if not os.getenv("STRIPE_SECRET_KEY"):
        logger.warning("STRIPE_SECRET_KEY not set; payment routes will fail")

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
            out, status = _api_error(
                "rate_limited",
                "Too many requests. Please wait about a minute, then try again.",
                429,
            )
            out.headers.setdefault("Retry-After", "60")
            return out, status
        flash("Too many requests. Please wait about a minute, then try again.", "error")
        return redirect(request.referrer or url_for("jobs"))

    @app.template_filter("slugify")
    def _slugify_filter(text: str) -> str:
        return _slugify(text or "")

    @app.template_filter("truncate_text")
    def _truncate_text_filter(s, length=220):
        s = s or ""
        if len(s) <= length:
            return s
        return s[:length].rsplit(" ", 1)[0] + "…"

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
    def landing():
        """Render the premium landing page."""
        # If someone hits /?title=... or /?country=..., redirect to /jobs
        if request.args.get("title") or request.args.get("country") or request.args.get("page"):
            return redirect(url_for("jobs", **request.args), 301)

        total_jobs = 0
        try:
            total_jobs = Job.count(None, None) or 0
        except Exception:
            pass

        featured_jobs = []
        try:
            rows = Job.search(None, None, limit=4, offset=0)
            for row in rows:
                featured_jobs.append({
                    "id": row.get("id"),
                    "title": (row.get("job_title") or "").strip(),
                    "company": row.get("company_name") or "",
                    "location": row.get("location") or "Remote",
                })
        except Exception:
            pass

        return render_template(
            "landing.html",
            wide_layout=True,
            total_jobs=total_jobs,
            featured_jobs=featured_jobs,
        )

    @app.get("/jobs")
    @_exempt_public_jobs
    def jobs():
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

        # Explicit salary_min filter from ?salary_min= query param
        salary_min_filter: Optional[int] = None
        raw_salary_min = (request.args.get("salary_min") or "").strip()
        if raw_salary_min:
            try:
                salary_min_filter = max(0, int(raw_salary_min))
            except ValueError:
                pass

        adv_filters: Dict[str, Any] = {}
        if request.args.get("remote"):
            adv_filters["remote"] = True
        if request.args.get("has_salary"):
            adv_filters["has_salary"] = True
        raw_freshness = (request.args.get("freshness") or "").strip()
        if raw_freshness in ("7", "14", "30"):
            adv_filters["freshness"] = int(raw_freshness)
        raw_function = (request.args.get("function") or "").strip()
        if raw_function:
            adv_filters["function_cat"] = raw_function
        raw_salary_max = (request.args.get("salary_max") or "").strip()
        if raw_salary_max:
            try:
                adv_filters["salary_max"] = max(0, int(raw_salary_max))
            except ValueError:
                pass

        total = 0
        rows = []
        try:
            total = Job.count(q_title, q_country, salary_min=salary_min_filter, **adv_filters)
            offset = (max(1, page) - 1) * per_page
            rows = Job.search(q_title, q_country, limit=per_page, offset=offset, salary_min=salary_min_filter, **adv_filters)
        except Exception:
            logger.exception("Job lookup failed during index rendering")
            rows = []
            total = 0

        # Freemium gate: anonymous users get up to 5K jobs per day across all searches
        subscribe_gate = False
        _remaining = _guest_daily_remaining()
        if _remaining != -1 and (q_title or q_country):
            if _remaining <= 0:
                subscribe_gate = True
                rows = []
                total = 0
            else:
                rows = rows[:_remaining]
                total = min(total, _remaining)
                _guest_daily_consume(len(rows))
                if _remaining < 20:          # near limit: show soft warning
                    subscribe_gate = True

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
                    title_lc = title.lower()
                    if any(k in title_lc for k in TITLE_BUCKET2_KEYWORDS):
                        uplift_factor = 1.10
                    elif any(k in title_lc for k in TITLE_BUCKET1_KEYWORDS):
                        uplift_factor = 1.05

                    base_rng = salary_range_around(float(median), pct=0.2)
                    if base_rng:
                        base_low, base_high, base_low_s, base_high_s = base_rng
                        base_median_compact = _compact_salary_number(float(median))

                        if uplift_factor > 1.0:
                            uplift_amount = float(median) * (uplift_factor - 1.0)
                            adj_low = base_low + uplift_amount
                            adj_high = base_high + uplift_amount
                            low_s = _compact_salary_number(adj_low)
                            high_s = _compact_salary_number(adj_high)
                            range_compact = (int(adj_low), int(adj_high))
                            estimated_display = f"{low_s}\u2013{high_s}"
                        else:
                            range_compact = (base_low, base_high)
                            estimated_display = f"{base_low_s}\u2013{base_high_s}"

                        median_compact = base_median_compact
                except Exception:
                    range_compact = None

            salary_delta_pct = None
            if median is not None and range_compact and len(range_compact) >= 2:
                try:
                    lo, hi = float(range_compact[0]), float(range_compact[1])
                    mid_est = (lo + hi) / 2.0
                    med = float(median)
                    if med > 0:
                        salary_delta_pct = int(round((mid_est - med) / med * 100))
                except Exception:
                    salary_delta_pct = None

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
                "salary_delta_pct": salary_delta_pct,
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

            try:
                _sal_ref = (median, currency) if median is not None else None
                _ref_lvl = "city" if median is not None else "none"
                _comp = compute_compensation_confidence(
                    {
                        "salary": row.get("salary") or "",
                        "job_salary": row.get("job_salary"),
                        "salary_min": range_compact[0] if range_compact else None,
                        "salary_max": range_compact[1] if range_compact else None,
                        "median_salary_currency": currency,
                    },
                    _sal_ref,
                    has_crowd_data=False,
                    ref_match_level=_ref_lvl,
                )
                item_payload["comp_confidence"] = _comp["confidence"]
            except Exception:
                item_payload["comp_confidence"] = None

            try:
                _qs = compute_quality_score(row)
                item_payload["quality_score"] = _qs["total"]
            except Exception:
                item_payload["quality_score"] = None

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
            "prev_url": url_for(
                "jobs",
                title=title_q or None,
                country=(raw_country or None),
                salary_min=salary_min_filter,
                page=page - 1,
            )
            if page > 1
            else None,
            "next_url": url_for(
                "jobs",
                title=title_q or None,
                country=(raw_country or None),
                salary_min=salary_min_filter,
                page=page + 1,
            )
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
            subscribe_gate=subscribe_gate,
            jobs_salary_min=salary_min_filter,
        )

    @app.get("/remote")
    def remote_jobs():
        """301 redirect to remote jobs filter; preserves SEO equity for /remote URL."""
        return redirect(url_for("jobs", country="Remote"), 301)

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

        # Freemium gate for API: anonymous users get up to 5K jobs per day
        _remaining = _guest_daily_remaining()
        if _remaining != -1:
            if _remaining <= 0:
                rows = []
                total = 0
            else:
                rows = rows[:_remaining]
                total = min(total if total is not None else 0, _remaining)
                _guest_daily_consume(len(rows))

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
            return redirect(url_for("jobs"))
        if honeypot_triggered(payload):
            if is_json:
                return jsonify({"error": "invalid_request"}), 400
            flash("Unable to complete that request. Please refresh the page and try again.", "error")
            return redirect(url_for("jobs"))
        email = (payload.get("email") or "").strip()
        job_id_raw = (payload.get("job_id") or "").strip()
        search_title = (payload.get("search_title") or "").strip()
        search_country = (payload.get("search_country") or "").strip()
        search_salary_band = (payload.get("search_salary_band") or "").strip()
        search_title, search_country, search_salary_band = sanitize_subscriber_search_fields(
            search_title, search_country, search_salary_band
        )
        digest_label_parts = [p for p in [search_title, search_country, search_salary_band] if p]
        digest_label = " / ".join(digest_label_parts[:3])

        try:
            email = validate_email(email, check_deliverability=False).normalized
        except EmailNotValidError:
            if is_json:
                return jsonify({"error": "invalid_email"}), 400
            flash("Please enter a valid email.", "error")
            return redirect(url_for("jobs"))

        if disposable_email_domain(email):
            if is_json:
                return jsonify({"error": "invalid_email"}), 400
            flash("Please use a permanent email address.", "error")
            return redirect(url_for("jobs"))

        job_link = Job.get_link(job_id_raw)
        next_url = (payload.get("next") or "").strip()
        if not job_link and next_url and _is_safe_redirect_target(next_url):
            job_link = next_url
        status = insert_subscriber(email, search_title=search_title, search_country=search_country, search_salary_band=search_salary_band)

        # Unlock freemium access for this session on successful subscribe or duplicate
        if status in ("ok", "duplicate"):
            session["subscribed"] = True
            session.modified = True

        if job_link:
            if status == "error":
                if is_json:
                    return jsonify({"error": "subscribe_failed"}), 500
                flash("We couldn't process your email. Please try again later.", "error")
                return redirect(url_for("jobs"))
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
            send_subscribe_welcome(email, digest_label)
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
            return redirect(url_for("jobs"))

        if is_json:
            body = {"status": status or "ok"}
            if job_link:
                body["redirect"] = job_link
            return jsonify(body), 200
        return redirect(url_for("jobs"))

    # /subscribe.json removed — POST /subscribe detects request.is_json automatically

    @app.route("/register", methods=["GET", "POST"])
    @_limit("10 per minute")
    def register():
        if session.get("user"):
            return redirect(url_for("studio"))
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

    @app.post("/auth/forgot")
    @_limit("5 per minute")
    def auth_forgot_password():
        """Request Supabase password recovery email (no email enumeration in UI copy)."""
        if session.get("user"):
            return redirect(url_for("studio"))
        if not _csrf_valid():
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("register", tab="login"))
        email = (request.form.get("email") or "").strip()
        try:
            email = validate_email(email, check_deliverability=False).normalized
        except Exception:
            flash(
                "If an account exists for that address, we sent password reset instructions.",
                "info",
            )
            return redirect(url_for("register", tab="login"))
        sb = _get_supabase()
        if sb:
            try:
                redirect_url = url_for("auth_confirm", _external=True)
                sb.auth.reset_password_for_email(email, {"redirect_to": redirect_url})
            except Exception as exc:
                logger.warning("auth forgot email=%s: %s", email, exc)
        flash(
            "If an account exists for that address, we sent password reset instructions.",
            "info",
        )
        return redirect(url_for("register", tab="login"))

    @app.get("/auth/confirm")
    def auth_confirm():
        """Landing page after Supabase redirects with tokens in the URL fragment (implicit flow)."""
        if session.get("user"):
            return redirect(url_for("studio"))
        return render_template("auth_confirm.html")

    @app.post("/auth/session")
    @_limit("30 per minute")
    def auth_session_from_tokens():
        """Exchange Supabase access_token for a Flask session (used after email recovery link)."""
        if not _csrf_valid():
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
            return jsonify({"ok": True, "redirect": url_for("studio")})
        except Exception as exc:
            logger.warning("auth session from tokens: %s", exc)
            return jsonify({"ok": False, "error": "invalid_token"}), 401

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        if request.method == "GET":
            return redirect(url_for("jobs"))
        if not _csrf_valid():
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("jobs"))
        session.pop("user", None)
        return redirect(url_for("jobs"))

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
        return redirect(url_for("jobs"))

    @app.get("/studio")
    def studio():
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))
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

    @app.get("/docs/api")
    def docs_api():
        """Public developer reference for the Catalitium HTTP API."""
        return render_template("docs_api.html")

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

    @app.get("/post-job")
    def post_job_form():
        """Full-page job posting form for authenticated recruiters/companies."""
        user = session.get("user")
        if not user:
            return redirect(url_for("register"))

        account_type = (user.get("account_type") or "").lower()
        hire_access = bool(user.get("hire_access"))

        if not _is_hire_eligible(account_type, hire_access):
            flash(
                "Job posting is available for recruiter and company accounts. "
                "Complete your company setup to continue.",
                "error",
            )
            return redirect(url_for("hire_onboarding"))

        user_id = str(user.get("id") or "").strip()
        if not user_id:
            session.pop("user", None)
            return redirect(url_for("register"))

        hire_data, err = _get_hire_metadata(user_id)
        if err and err != "Auth service unavailable.":
            flash(err, "error")
        return render_template("post_job_form.html", user=user, hire=hire_data)

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
            return redirect(url_for("jobs"))
        if honeypot_triggered(payload):
            if is_json:
                return jsonify({"error": "invalid_request"}), 400
            flash("Unable to complete that request. Please refresh the page and try again.", "error")
            return redirect(url_for("jobs"))
        email_raw = (payload.get("email") or "").strip()
        name_raw = (payload.get("name") or payload.get("name_company") or payload.get("company") or "").strip()
        message_raw = (payload.get("message") or "").strip()

        try:
            email = validate_email(email_raw, check_deliverability=False).normalized
        except EmailNotValidError:
            if is_json:
                return jsonify({"error": "invalid_email"}), 400
            flash("Please enter a valid email.", "error")
            return redirect(url_for("jobs"))

        if disposable_email_domain(email):
            if is_json:
                return jsonify({"error": "invalid_email"}), 400
            flash("Please use a permanent email address.", "error")
            return redirect(url_for("jobs"))

        if not name_raw or len(name_raw) < 2:
            if is_json:
                return jsonify({"error": "invalid_name"}), 400
            flash("Please add your name or company.", "error")
            return redirect(url_for("jobs"))

        if not message_raw or len(message_raw) < 5:
            if is_json:
                return jsonify({"error": "invalid_message"}), 400
            flash("Please add a short message.", "error")
            return redirect(url_for("jobs"))

        prepared = prepare_contact_submission(name_raw, message_raw)
        if prepared is None:
            if is_json:
                return jsonify({"error": "invalid_message"}), 400
            flash("Your message could not be sent. Please shorten links or remove unusual text and try again.", "error")
            return redirect(url_for("jobs"))
        name_clean, msg_clean = prepared

        status = insert_contact(email=email, name_company=name_clean, message=msg_clean)

        if status != "ok":
            if is_json:
                return jsonify({"error": "contact_failed"}), 500
            flash("We could not send your message. Please try again.", "error")
            return redirect(url_for("jobs"))

        if is_json:
            return jsonify({"status": "ok"}), 200
        flash("Thanks! We received your message.", "success")
        return redirect(url_for("jobs"))

    # /contact.json removed — POST /contact detects request.is_json automatically

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

        # --- Plan check (Elite/Premium gate; integration pending) ---
        # Uncomment when payment tiers are live:
        # user_plan = (user.get("plan") or "free").lower()
        # if user_plan not in ("elite", "premium"):
        #     if is_json:
        #         return jsonify({"error": "plan_upgrade_required"}), 403
        #     flash("Upgrade to Elite or Premium to post jobs.", "error")
        #     return redirect(url_for("stripe_routes.pricing"))

        user_id = str(user.get("id") or "").strip() or None

        if not _csrf_valid():
            if is_json:
                return jsonify({"error": "invalid_csrf"}), 400
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("jobs"))

        contact_email_raw = (payload.get("contact_email") or payload.get("email") or "").strip()
        job_title_raw = (payload.get("job_title") or "").strip()
        company_raw = (payload.get("company") or "").strip()
        description_raw = (payload.get("description") or "").strip()
        salary_range_raw = (payload.get("salary_range") or "").strip()
        location_raw = (payload.get("location") or "").strip()
        employment_type_raw = (payload.get("employment_type") or "").strip()
        work_arrangement_raw = (payload.get("work_arrangement") or "").strip()
        apply_url_raw = (payload.get("apply_url") or "").strip()

        try:
            contact_email = validate_email(contact_email_raw, check_deliverability=False).normalized
        except EmailNotValidError:
            if is_json:
                return jsonify({"error": "invalid_email"}), 400
            flash("Please enter a valid contact email.", "error")
            return redirect(url_for("post_job_form"))

        def _word_count(text: str) -> int:
            if not text:
                return 0
            return len(re.findall(r"\b\w+\b", text))

        if len(job_title_raw) < 2:
            if is_json:
                return jsonify({"error": "invalid_title"}), 400
            flash("Please add a job title.", "error")
            return redirect(url_for("post_job_form"))

        if len(company_raw) < 2:
            if is_json:
                return jsonify({"error": "invalid_company"}), 400
            flash("Please add a company name.", "error")
            return redirect(url_for("post_job_form"))

        if len(description_raw) < 10:
            if is_json:
                return jsonify({"error": "invalid_description"}), 400
            flash("Please add a short description.", "error")
            return redirect(url_for("post_job_form"))

        if _word_count(description_raw) > 5000:
            if is_json:
                return jsonify({"error": "description_too_long"}), 400
            flash("Description is too long (max ~5000 words).", "error")
            return redirect(url_for("post_job_form"))

        # Enrich description with additional fields
        description_full = description_raw
        if location_raw:
            description_full = f"Location: {location_raw}\n\n{description_full}"
        if employment_type_raw:
            description_full += f"\n\nEmployment type: {employment_type_raw}"
        if work_arrangement_raw:
            description_full += f"\nWork arrangement: {work_arrangement_raw}"
        if apply_url_raw:
            description_full += f"\n\nApply here: {apply_url_raw}"

        status = insert_job_posting(
            contact_email=contact_email,
            job_title=job_title_raw,
            company=company_raw,
            description=description_full,
            salary_range=salary_range_raw,
            user_id=user_id,
        )

        if status != "ok":
            if is_json:
                return jsonify({"error": "job_posting_failed"}), 500
            flash("We could not submit the job. Please try again.", "error")
            return redirect(url_for("post_job_form"))

        if is_json:
            return jsonify({"status": "ok"}), 200
        flash("Your job has been submitted and will go live within 24 hours.", "success")
        return redirect(url_for("hire"))

    # /job-posting.json removed — POST /job-posting detects request.is_json automatically

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
        """Return distinct job title or company suggestions for autocomplete."""
        q = parse_str_arg(request.args, "q", default="", max_len=80).lower()
        ac_type = parse_str_arg(request.args, "type", default="title", max_len=10)
        if len(q) < 2:
            return _api_success({"suggestions": []})
        cache_key = f"autocomplete:{ac_type}:{q}"
        cached = autocomplete_cache.get(cache_key)
        if cached is not None:
            return _api_success(cached)
        try:
            db = get_db()
            with db.cursor() as cur:
                if ac_type == "company":
                    cur.execute(
                        "SELECT DISTINCT company_name FROM jobs "
                        "WHERE LOWER(company_name) LIKE %s AND company_name IS NOT NULL "
                        "ORDER BY company_name LIMIT 8",
                        (f"%{q}%",),
                    )
                else:
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
            "jobs",
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

    # Stripe + payment routes → app.routes.stripe_routes blueprint
    # (B2C subscriptions, B2B checkout, webhooks moved to routes/stripe_routes.py)

    # [Stripe helpers + routes removed — see app/routes/stripe_routes.py]
    @app.get("/health")
    def health():
        """Expose a readiness probe indicating the database is reachable."""
        rid = getattr(g, "request_id", "")
        deep = (request.args.get("deep") or "").strip().lower() in {"1", "true", "yes", "on"}
        t0 = time.perf_counter()
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
                if deep:
                    cur.execute("SELECT current_database()")
                    cur.fetchone()
        except Exception:
            logger.warning("health check failed request_id=%s deep=%s", rid, deep)
            return _api_error("db_unavailable", "Database connection failed", 503)
        latency_ms = round((time.perf_counter() - t0) * 1000, 3)
        payload: Dict[str, Any] = {
            "status": "ok",
            "db": "connected",
            "db_latency_ms": latency_ms,
        }
        if deep:
            payload["deep"] = True
        logger.debug("health ok request_id=%s deep=%s", rid, deep)
        return _api_success(payload)

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
                "Disallow: /profile",
                "Disallow: /subscription/",
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

    # Explore routes → app.routes.explore blueprint

    @app.get("/sitemap.xml")
    def sitemap():
        """Generate a lightweight XML sitemap for primary surfaces."""
        import time as _time
        if _sitemap_cache["data"] and _time.time() - _sitemap_cache["ts"] < SITEMAP_CACHE_TTL:
            return _sitemap_cache["data"]
        today = datetime.now(timezone.utc).date().isoformat()
        urls = []
        most_recent_date: Optional[str] = None

        def _add(loc: str, priority: str = "0.5", lastmod: str = today, changefreq: str = "weekly"):
            if loc:
                urls.append({"loc": loc, "priority": priority, "lastmod": lastmod, "changefreq": changefreq})

        _add(url_for("jobs", _external=True), priority="1.0", changefreq="daily")
        _add(url_for("landing", _external=True), priority="0.95", changefreq="weekly")
        _add(url_for("stripe_routes.pricing", _external=True), priority="0.75", changefreq="weekly")
        _add(url_for("developers", _external=True), priority="0.65", changefreq="monthly")
        _add(url_for("companies.companies", _external=True), priority="0.8", changefreq="weekly")
        _add(url_for("explore.explore_hub", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("explore.explore_remote", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("explore.explore_functions", _external=True), priority="0.7", changefreq="weekly")

        # Top company profile pages
        try:
            _top_companies = Job.company_list(limit=50)
            for _tc in _top_companies:
                _cn = _tc.get("company_name") or ""
                _cs = _slugify(_cn)
                if _cs:
                    _add(url_for("companies.company_detail_page", slug=_cs, _external=True),
                         priority="0.6", changefreq="weekly")
        except Exception as _exc:
            logger.debug("sitemap company entries failed: %s", _exc)
        _add(url_for("about", _external=True), priority="0.8", changefreq="monthly")
        _add(url_for("resources", _external=True), priority="0.9", changefreq="weekly")
        _add(url_for("market_research_index", _external=True), priority="0.9", changefreq="weekly")
        for _r in REPORTS:
            _add(url_for("market_research_report", slug=_r["slug"], _external=True), priority="0.85", changefreq="monthly")
        _add(url_for("recruiter_salary_board", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("salary.salary_tool", _external=True), priority="0.85", changefreq="weekly")
        _add(url_for("salary.salary_by_title", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("salary.salary_top_companies", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("salary.salary_underpaid", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("salary.salary_compare_cities", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("salary.salary_by_function", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("salary.salary_trends", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("salary.compensation_methodology", _external=True), priority="0.6", changefreq="monthly")
        _add(url_for("hire", _external=True), priority="0.8", changefreq="monthly")
        _add(url_for("stripe_routes.post_a_job", _external=True), priority="0.75", changefreq="monthly")
        _add(url_for("docs_api", _external=True), priority="0.6", changefreq="monthly")
        _add(url_for("legal", _external=True), priority="0.2", changefreq="yearly")
        _add(url_for("tracker", _external=True), priority="0.6", changefreq="weekly")
        _add(url_for("career.career_evaluate", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("career.career_ai_exposure", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("career.career_hiring_trends", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("career.career_earnings", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("career.career_paths", _external=True), priority="0.7", changefreq="weekly")
        _add(url_for("career.career_market_position", _external=True), priority="0.7", changefreq="weekly")

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
            loc = url_for("jobs", title=target.get("title"), country=target.get("country"), _external=True)
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
        resp.headers["Cache-Control"] = f"public, max-age={SITEMAP_CACHE_TTL}"
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
                title_lc = title.lower()
                uplift = 1.10 if any(k in title_lc for k in TITLE_BUCKET2_KEYWORDS) else (
                    1.05 if any(k in title_lc for k in TITLE_BUCKET1_KEYWORDS) else 1.0)
                base_rng = salary_range_around(float(median), pct=0.2)
                if base_rng:
                    base_low, base_high, base_low_s, base_high_s = base_rng
                    if uplift > 1.0:
                        amt = float(median) * (uplift - 1.0)
                        low_s = _compact_salary_number(base_low + amt)
                        high_s = _compact_salary_number(base_high + amt)
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

        # Compensation confidence scoring
        comp_display = None
        try:
            salary_ref = (median, currency) if median is not None else None
            ref_level = "city" if median is not None else "none"
            comp_display = compute_compensation_confidence(
                {
                    "salary": salary_range,
                    "job_salary": row.get("job_salary"),
                    "salary_min": salary_min,
                    "salary_max": salary_max,
                    "median_salary_currency": currency,
                },
                salary_ref,
                has_crowd_data=False,
                ref_match_level=ref_level,
                methodology_url=url_for("salary.compensation_methodology"),
            )
            comp_display["source_label"] = compensation_source_label(comp_display["source"])
        except Exception:
            comp_display = None

        company_slug = _slugify(company) if company else ""

        return render_template(
            "job_detail.html",
            job=job,
            related=related,
            ai_summary=ai_summary,
            comp_display=comp_display,
            company_slug=company_slug,
            subscribe_ctx={
                "title": title,
                "country": loc,
                "salary_band": detail_salary_band,
            },
        )

    # Salary routes → app.routes.salary blueprint

    # ------------------------------------------------------------------
    # Favicons / touch icons at well-known URLs (mobile browsers often
    # request /favicon.ico and /apple-touch-icon.png before parsing HTML).
    # ------------------------------------------------------------------
    _static_img_dir = os.path.join(os.path.dirname(__file__), "static", "img")

    @app.get("/favicon.ico")
    def favicon_ico():
        return send_from_directory(_static_img_dir, "favicon.ico", mimetype="image/x-icon")

    @app.get("/apple-touch-icon.png")
    @app.get("/apple-touch-icon-precomposed.png")
    def apple_touch_icon_well_known():
        return send_from_directory(
            _static_img_dir, "apple-touch-icon.png", mimetype="image/png"
        )

    # ------------------------------------------------------------------
    # Service worker (must be served from root scope)
    # ------------------------------------------------------------------
    @app.get("/sw.js")
    def service_worker():
        """Render the PWA service worker with ASSET_VERSION injected so cache busts on deploy."""
        asset_version = app.config.get("ASSET_VERSION", "v1")
        resp = Response(
            render_template("sw.js", asset_version=asset_version),
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

    # Companies routes → app.routes.companies blueprint

    # ------------------------------------------------------------------
    # Resources hub: 301 redirect to Market Research
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
        """Market Research hub: lists all published reports."""
        user = session.get("user")
        mi_tier = _get_mi_tier(user)
        return render_template(
            "market_research_index.html",
            reports=REPORTS,
            mi_tier=mi_tier,
            user=user,
        )

    @app.get("/developers")
    def developers():
        """Simple, human-facing overview of the v1 JSON API."""
        return render_template(
            "developers.html",
        )

    @app.get("/troy")
    def troy_redirect_carl():
        """Legacy path; Carl lives at ``/carl``."""
        return redirect(url_for("carl_dashboard"), code=301)

    @app.get("/carl")
    def carl_dashboard():
        """Render Carl CV dashboard demo page."""
        if not session.get("user"):
            session["redirect_after_login"] = url_for("carl_dashboard")
            flash("Sign in to use Carl.", "info")
            return redirect(url_for("register"))
        return render_template("carl.html", wide_layout=True)

    @app.post("/carl/analyze")
    @_limit("20 per minute")
    def carl_analyze():
        """Accept CV upload/text fallback and return deterministic mock analysis."""
        if not session.get("user"):
            return _api_error("login_required", "Sign in to analyze your CV in Carl.", 401)
        if not _csrf_valid():
            return _api_error("invalid_csrf", "Session expired. Please refresh and try again.", 400)

        upload = request.files.get("cv_file")
        text_fallback = (request.form.get("cv_text") or "").strip()
        if not upload and not text_fallback:
            return _api_error("missing_cv_input", "Upload a PDF/DOCX file or paste CV text.", 400)

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
            return _api_error(exc.code, exc.message, exc.status)

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
        return _api_success(
            {
                "analysis": analysis,
                "source": source,
                "profile_sync": profile_sync,
            }
        )

    @app.post("/carl/chat")
    @_limit("40 per minute")
    def carl_chat():
        """Return a rule-based mock chat reply for Carl dashboard."""
        if not session.get("user"):
            return _api_error("login_required", "Sign in to use Talk to Carl.", 401)
        if not _csrf_valid():
            return _api_error("invalid_csrf", "Session expired. Please refresh and try again.", 400)

        session_ctx = session.get("carl_chat_context") or {}
        if not session_ctx:
            return _api_error("carl_session_stale", "Analyze a CV first, then chat about that pass.", 400)

        turns = int(session.get("carl_chat_turns") or 0)
        if turns >= CARL_CHAT_MAX_TURNS:
            return _api_success(
                {
                    "reply": (
                        "You have used all free Talk to Carl prompts for this CV pass. "
                        "Unlock the Jobs API on Pricing or review integration on Developers."
                    ),
                    "chat_limit_reached": True,
                    "cta": {
                        "developers": url_for("developers"),
                        "pricing": url_for("stripe_routes.pricing"),
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
                return _api_error("invalid_prompt_id", "Invalid prompt selection.", 400)

        effective_message, pe_err = carl_effective_user_message(
            raw_message, session_ctx, prompt_id=prompt_id if has_prompt_id else None
        )
        if pe_err == "invalid_prompt_id":
            return _api_error("invalid_prompt_id", "Invalid prompt selection.", 400)
        if not effective_message:
            return _api_error("invalid_message", "Please write a message for Carl chat.", 400)
        if len(effective_message) > CARL_CHAT_MAX_MESSAGE_CHARS:
            return _api_error(
                "message_too_long",
                f"Keep messages under {CARL_CHAT_MAX_MESSAGE_CHARS} characters for this demo.",
                400,
            )

        if not is_carl_message_grounded(
            effective_message,
            session_ctx,
            prompt_id=prompt_id if has_prompt_id else None,
        ):
            return _api_error(
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
                "pricing": url_for("stripe_routes.pricing"),
            }
        return _api_success(out)

    @app.get("/market-research/<slug>")
    def market_research_report(slug):
        """Individual report landing page (fully SSR'd for SEO)."""
        report = next((r for r in REPORTS if r["slug"] == slug), None)
        if not report:
            abort(404)
        user = session.get("user")
        if not user:
            session["redirect_after_login"] = request.path
            flash("Sign in to read this report.", "info")
            return redirect(url_for("register"))
        mi_tier = _get_mi_tier(user)
        return render_template(
            report.get("template", "reports/report.html"),
            report=report,
            mi_tier=mi_tier,
            user=user,
        )

    # ------------------------------------------------------------------
    # API key + v1 routes + summary → app.routes.api_v1 blueprint

    # ------------------------------------------------------------------
    # Tracker (wire orphaned template)
    # ------------------------------------------------------------------
    @app.get("/tracker")
    def tracker():
        """Render the job application tracker page."""
        return render_template("tracker.html")

    # Career routes → app.routes.career blueprint

    return app
