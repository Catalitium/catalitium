"""Public job search, marketing pages, and lightweight JSON API routes."""

from __future__ import annotations

import json as _json
import os
import re
import time
import urllib.request as _urllib_req
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from ..config import SITEMAP_CACHE_TTL
from ..data.catalogs import DEMO_JOBS, REPORTS
from ..mailer import send_subscribe_welcome
from ..utils import guest_daily_consume, guest_daily_remaining
from ..models.catalog import (
    Job,
    clean_job_description_text,
    compute_quality_score,
    format_job_date_string,
    get_explore_data,
    get_function_distribution,
    get_job_summary,
    get_remote_companies,
)
from ..models.db import get_db, logger, parse_job_description
from ..models.billing import insert_job_posting
from ..models.subscribers import (
    honeypot_triggered,
    insert_contact,
    insert_subscriber,
    prepare_contact_submission,
    sanitize_subscriber_search_fields,
)
from ..models.money import (
    TITLE_BUCKET1_KEYWORDS,
    TITLE_BUCKET2_KEYWORDS,
    _compact_salary_number,
    compute_compensation_confidence,
    estimate_salary_display,
    get_salary_for_location,
    parse_salary_query,
    parse_salary_range_string,
    salary_range_around,
    source_label as compensation_source_label,
)
from ..utils import (
    AUTOCOMPLETE_CACHE,
    BLACKLIST_LINKS,
    EmailNotValidError,
    SALARY_CACHE,
    SUMMARY_CACHE,
    api_error_response,
    api_success_response,
    coerce_datetime as _coerce_datetime,
    csrf_valid,
    disposable_email_domain,
    job_is_ghost as _job_is_ghost,
    job_is_new as _job_is_new,
    normalize_country,
    normalize_title,
    parse_int_arg,
    parse_str_arg,
    resolve_pagination,
    slugify as _slugify,
    to_lc as _to_lc,
    validate_email,
)

bp = Blueprint("jobs", __name__)


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

ENVIRONMENT = os.getenv("FLASK_ENV") or os.getenv("ENV") or "production"

# Email/data functions consolidated in app/utils.py.


_sitemap_cache: dict = {"data": None, "ts": 0.0}



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

def display_per_page(per_page: int) -> int:
    """Return the value surfaced in pagination metadata."""
    if per_page < 5:
        return per_page
    return max(per_page, 10)


def query_jobs_payload(*, raw_title: str, raw_country: str, page: int, per_page: int) -> Dict[str, Any]:
    """Shared jobs listing payload for /api/jobs and /v1/jobs."""
    per_page_display = display_per_page(per_page)

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
    _remaining = guest_daily_remaining()
    if _remaining != -1:
        if _remaining <= 0:
            rows = []
            total = 0
        else:
            rows = rows[:_remaining]
            total = min(total if total is not None else 0, _remaining)
            guest_daily_consume(len(rows))

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

@bp.get("/")
def landing():
    """Render the premium landing page."""
    # If someone hits /?title=... or /?country=..., redirect to /jobs
    if request.args.get("title") or request.args.get("country") or request.args.get("page"):
        return redirect(url_for("jobs.jobs", **request.args), 301)

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
        "jobs/landing.html",
        wide_layout=True,
        total_jobs=total_jobs,
        featured_jobs=featured_jobs,
    )

@bp.get("/jobs")
def jobs():
    """Render the main job search page with optional filters."""
    raw_title = (request.args.get("title") or "").strip()
    raw_country = (request.args.get("country") or "").strip()
    page, per_page = resolve_pagination()
    per_page_display = display_per_page(per_page)

    title_q, country_q, sal_floor, sal_ceiling = safe_parse_search_params(raw_title, raw_country)
    if raw_title and not title_q:
        title_q = normalize_title(raw_title)
    if raw_country and not country_q:
        country_q = normalize_country(raw_country)
    if title_q:
        title_q = str(title_q).strip() or None
    if country_q:
        country_q = str(country_q).strip() or None

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
    _remaining = guest_daily_remaining()
    if _remaining != -1 and (q_title or q_country):
        if _remaining <= 0:
            subscribe_gate = True
            rows = []
            total = 0
        else:
            rows = rows[:_remaining]
            total = min(total, _remaining)
            guest_daily_consume(len(rows))
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
        items = DEMO_JOBS
        total = len(DEMO_JOBS)
        page = 1
        per_page = len(DEMO_JOBS)
        per_page_display = display_per_page(per_page)

    per_page_display = display_per_page(per_page)
    pages_display = max(1, (total + per_page_display - 1) // per_page_display) if total else 1

    pagination = {
        "page": page,
        "pages": pages_display,
        "total": total,
        "per_page": per_page_display,
        "has_prev": page > 1,
        "has_next": page < pages_display,
        "prev_url": url_for(
            "jobs.jobs",
            title=title_q or None,
            country=(raw_country or None),
            salary_min=salary_min_filter,
            page=page - 1,
        )
        if page > 1
        else None,
        "next_url": url_for(
            "jobs.jobs",
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
        "jobs/job_search.html",
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

@bp.get("/remote")
def remote_jobs():
    """301 redirect to remote jobs filter; preserves SEO equity for /remote URL."""
    return redirect(url_for("jobs.jobs", country="Remote"), 301)

@bp.get("/recruiter-salary-board")
def recruiter_salary_board():
    """Surface the dedicated job browser experience."""
    job_api_url = url_for("jobs.api_jobs")
    return render_template(
        "jobs/job_browser.html",
        job_api=job_api_url,
    )


@bp.get("/api/jobs")
def api_jobs():
    """Return jobs as JSON with pagination metadata."""
    raw_title = parse_str_arg(request.args, "title", default="", max_len=120)
    raw_country = parse_str_arg(request.args, "country", default="", max_len=80)
    page, per_page = resolve_pagination()
    payload = query_jobs_payload(raw_title=raw_title, raw_country=raw_country, page=page, per_page=per_page)
    return api_success_response(payload)

@bp.get("/api/jobs/summary")
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
    cached = SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return api_success_response(cached)

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
    SUMMARY_CACHE.set(cache_key, payload)
    return api_success_response(payload)

@bp.post("/subscribe")
def subscribe():
    """Handle newsletter subscriptions from form or JSON payloads."""
    is_json = request.is_json
    payload = request.get_json(silent=True) or {} if is_json else request.form
    if not csrf_valid():
        if is_json:
            return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("jobs.jobs"))
    if honeypot_triggered(payload):
        if is_json:
            return api_error_response("invalid_request", "Invalid request.", 400)
        flash("Unable to complete that request. Please refresh the page and try again.", "error")
        return redirect(url_for("jobs.jobs"))
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
            return api_error_response("invalid_email", "Please provide a valid email.", 400)
        flash("Please enter a valid email.", "error")
        return redirect(url_for("jobs.jobs"))

    if disposable_email_domain(email):
        if is_json:
            return api_error_response("invalid_email", "Please provide a valid email.", 400)
        flash("Please use a permanent email address.", "error")
        return redirect(url_for("jobs.jobs"))

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
                return api_error_response("subscribe_failed", "Could not complete subscription.", 500)
            flash("We couldn't process your email. Please try again later.", "error")
            return redirect(url_for("jobs.jobs"))
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
            dup_data = {
                "status": "duplicate",
                "digest": {
                    "title": search_title,
                    "country": search_country,
                    "salary_band": search_salary_band,
                },
            }
            if job_link:
                dup_data["redirect"] = job_link
            return api_success_response(
                dup_data,
                code="duplicate",
                message="Already subscribed",
            )
        flash("You're already subscribed to the weekly digest.", "success")
    else:
        if is_json:
            return api_error_response("subscribe_failed", "Could not complete subscription.", 500)
        flash("We couldn't process your email. Please try again later.", "error")
        return redirect(url_for("jobs.jobs"))

    if is_json:
        body = {"status": status or "ok"}
        if job_link:
            body["redirect"] = job_link
        return jsonify(body), 200
    return redirect(url_for("jobs.jobs"))

# /subscribe.json removed — POST /subscribe detects request.is_json automatically

@bp.post("/contact")
def contact():
    """Handle contact form submissions (JSON or form)."""
    is_json = request.is_json
    payload = request.get_json(silent=True) or {} if is_json else request.form
    if not csrf_valid():
        if is_json:
            return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("jobs.jobs"))
    if honeypot_triggered(payload):
        if is_json:
            return api_error_response("invalid_request", "Invalid request.", 400)
        flash("Unable to complete that request. Please refresh the page and try again.", "error")
        return redirect(url_for("jobs.jobs"))
    email_raw = (payload.get("email") or "").strip()
    name_raw = (payload.get("name") or payload.get("name_company") or payload.get("company") or "").strip()
    message_raw = (payload.get("message") or "").strip()

    try:
        email = validate_email(email_raw, check_deliverability=False).normalized
    except EmailNotValidError:
        if is_json:
            return api_error_response("invalid_email", "Please provide a valid email.", 400)
        flash("Please enter a valid email.", "error")
        return redirect(url_for("jobs.jobs"))

    if disposable_email_domain(email):
        if is_json:
            return api_error_response("invalid_email", "Please provide a valid email.", 400)
        flash("Please use a permanent email address.", "error")
        return redirect(url_for("jobs.jobs"))

    if not name_raw or len(name_raw) < 2:
        if is_json:
            return api_error_response("invalid_name", "Name or company is required.", 400)
        flash("Please add your name or company.", "error")
        return redirect(url_for("jobs.jobs"))

    if not message_raw or len(message_raw) < 5:
        if is_json:
            return api_error_response("invalid_message", "Message is too short or invalid.", 400)
        flash("Please add a short message.", "error")
        return redirect(url_for("jobs.jobs"))

    prepared = prepare_contact_submission(name_raw, message_raw)
    if prepared is None:
        if is_json:
            return api_error_response("invalid_message", "Message is too short or invalid.", 400)
        flash("Your message could not be sent. Please shorten links or remove unusual text and try again.", "error")
        return redirect(url_for("jobs.jobs"))
    name_clean, msg_clean = prepared

    status = insert_contact(email=email, name_company=name_clean, message=msg_clean)

    if status != "ok":
        if is_json:
            return api_error_response("contact_failed", "Could not send your message.", 500)
        flash("We could not send your message. Please try again.", "error")
        return redirect(url_for("jobs.jobs"))

    if is_json:
        return jsonify({"status": "ok"}), 200
    flash("Thanks! We received your message.", "success")
    return redirect(url_for("jobs.jobs"))

# /contact.json removed — POST /contact detects request.is_json automatically

@bp.post("/job-posting")
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
            return api_error_response("auth_required", "Sign in to post a job.", 401)
        flash("Sign in to post a job.", "error")
        return redirect(url_for("auth.register"))

    account_type = (user.get("account_type") or "").lower()
    if account_type not in ("recruiter", "company"):
        if is_json:
            return api_error_response(
                "recruiter_account_required",
                "Job posting requires a recruiter or company account.",
                403,
            )
        flash("Job posting is available for recruiter and company accounts only.", "error")
        return redirect(url_for("auth.hire_onboarding"))

    # --- Plan check (Elite/Premium gate; integration pending) ---
    # Uncomment when payment tiers are live:
    # user_plan = (user.get("plan") or "free").lower()
    # if user_plan not in ("elite", "premium"):
    #     if is_json:
    #         return jsonify({"error": "plan_upgrade_required"}), 403
    #     flash("Upgrade to Elite or Premium to post jobs.", "error")
    #     return redirect(url_for("payments.pricing"))

    user_id = str(user.get("id") or "").strip() or None

    if not csrf_valid():
        if is_json:
            return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("jobs.jobs"))

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
            return api_error_response("invalid_email", "Please provide a valid email.", 400)
        flash("Please enter a valid contact email.", "error")
        return redirect(url_for("auth.post_job_form"))

    def _word_count(text: str) -> int:
        if not text:
            return 0
        return len(re.findall(r"\b\w+\b", text))

    if len(job_title_raw) < 2:
        if is_json:
            return api_error_response("invalid_title", "Please add a job title.", 400)
        flash("Please add a job title.", "error")
        return redirect(url_for("auth.post_job_form"))

    if len(company_raw) < 2:
        if is_json:
            return api_error_response("invalid_company", "Please add a company name.", 400)
        flash("Please add a company name.", "error")
        return redirect(url_for("auth.post_job_form"))

    if len(description_raw) < 10:
        if is_json:
            return api_error_response("invalid_description", "Please add a job description.", 400)
        flash("Please add a short description.", "error")
        return redirect(url_for("auth.post_job_form"))

    if _word_count(description_raw) > 5000:
        if is_json:
            return api_error_response("description_too_long", "Description is too long.", 400)
        flash("Description is too long (max ~5000 words).", "error")
        return redirect(url_for("auth.post_job_form"))

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
            return api_error_response("job_posting_failed", "Could not submit the job posting.", 500)
        flash("We could not submit the job. Please try again.", "error")
        return redirect(url_for("auth.post_job_form"))

    if is_json:
        return jsonify({"status": "ok"}), 200
    flash("Your job has been submitted and will go live within 24 hours.", "success")
    return redirect(url_for("auth.hire"))

# /job-posting.json removed — POST /job-posting detects request.is_json automatically

@bp.get("/api/salary-insights")
def api_salary_insights():
    """Return a lightweight public dataset of jobs for salary insights."""
    raw_title = parse_str_arg(request.args, "title", default="", max_len=120)
    raw_country = parse_str_arg(request.args, "country", default="", max_len=80)
    limit = parse_int_arg(request.args, "limit", default=100, minimum=1, maximum=300)
    cache_key = f"salary-insights:{raw_title.lower()}|{raw_country.lower()}|{limit}"
    cached = SALARY_CACHE.get(cache_key)
    if cached is not None:
        return api_success_response(cached)
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
    SALARY_CACHE.set(cache_key, payload)
    return api_success_response(payload)

@bp.get("/api/autocomplete")
def api_autocomplete():
    """Return distinct job title or company suggestions for autocomplete."""
    q = parse_str_arg(request.args, "q", default="", max_len=80).lower()
    ac_type = parse_str_arg(request.args, "type", default="title", max_len=10)
    if len(q) < 2:
        return api_success_response({"suggestions": []})
    cache_key = f"autocomplete:{ac_type}:{q}"
    cached = AUTOCOMPLETE_CACHE.get(cache_key)
    if cached is not None:
        return api_success_response(cached)
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
    AUTOCOMPLETE_CACHE.set(cache_key, payload)
    return api_success_response(payload)

@bp.get("/api/share-search")
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
        maximum=int(current_app.config.get("PER_PAGE_MAX", 100)),
    )

    canonical_url = url_for(
        "jobs.jobs",
        title=title or None,
        country=country or None,
        page=page,
        per_page=per_page,
        _external=True,
    )
    return api_success_response(
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

@bp.get("/api/salary/compare")
def api_salary_compare():
    """Compare salary baselines between two regions/locations for a role."""
    role = parse_str_arg(request.args, "role", default="", max_len=120)
    region_a = parse_str_arg(request.args, "region_a", default="", max_len=120)
    region_b = parse_str_arg(request.args, "region_b", default="", max_len=120)
    if not region_a or not region_b:
        return api_error_response(
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
        return api_error_response(
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

    return api_success_response(
        {
            "role": normalize_title(role) if role else "",
            "region_a": {"name": region_a, "median": median_a, "currency": sal_a[1] if sal_a else None},
            "region_b": {"name": region_b, "median": median_b, "currency": sal_b[1] if sal_b else None},
            "delta": delta,
            "delta_pct": delta_pct,
        }
    )

@bp.post("/studio-contact")
def studio_contact():
    """Minimal B2B studio intake endpoint reusing contact storage."""
    if not csrf_valid():
        return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)
    payload = request.get_json(silent=True) or request.form or {}
    email_raw = (payload.get("email") or "").strip()
    name_raw = (payload.get("name") or payload.get("company") or "").strip()
    priority = (payload.get("priority") or "").strip()
    message_raw = (payload.get("message") or "").strip()

    if not email_raw or not name_raw:
        return api_error_response(
            "invalid_params",
            "email and name/company are required",
            400,
            details={"required": ["email", "name"]},
        )
    try:
        email = validate_email(email_raw, check_deliverability=False).normalized
    except EmailNotValidError:
        return api_error_response("invalid_email", "Please provide a valid email", 400)

    tagged_message = (
        "[Studio enquiry]\n"
        f"Priority: {priority or 'unspecified'}\n"
        f"Path: {request.path}\n"
        f"Message: {message_raw or 'N/A'}"
    )
    status = insert_contact(email=email, name_company=name_raw, message=tagged_message)
    if status != "ok":
        return api_error_response("contact_failed", "Unable to submit studio enquiry", 500)
    return api_success_response({"status": "ok"}, 201, code="created", message="Studio enquiry submitted")

# Stripe + B2B checkout + webhooks → ``app/controllers/payments.py`` (blueprint ``payments``, registered in ``app/controllers/__init__.py``).
@bp.get("/health")
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
        return api_error_response("db_unavailable", "Database connection failed", 503)
    latency_ms = round((time.perf_counter() - t0) * 1000, 3)
    payload: Dict[str, Any] = {
        "status": "ok",
        "db": "connected",
        "db_latency_ms": latency_ms,
    }
    if deep:
        payload["deep"] = True
    logger.debug("health ok request_id=%s deep=%s", rid, deep)
    return api_success_response(payload)

@bp.get("/legal")
def legal():
    """Display combined privacy policy and terms information."""
    return render_template("site/legal.html")

def _robots_crawl_directives() -> list[str]:
    """Shared allow/disallow lines for default and named AI crawlers."""
    return [
        "Allow: /",
        "Disallow: /api/keys/",
        "Disallow: /v1/",
        "Disallow: /health",
        "Disallow: /profile",
        "Disallow: /subscription/",
    ]


@bp.get("/robots.txt")
def robots_txt():
    """Expose robots.txt with sitemap reference and crawl directives."""
    parts: list[str] = ["User-agent: *", *_robots_crawl_directives(), ""]
    for ua in ("GPTBot", "ClaudeBot", "PerplexityBot", "CCBot"):
        parts.extend([f"User-agent: {ua}", *_robots_crawl_directives(), ""])
    parts.extend(
        [
            "User-agent: AdsBot-Google",
            "Allow: /",
            "",
            "User-agent: Googlebot-Image",
            "Allow: /static/img/",
            "",
            f"Sitemap: {url_for('jobs.sitemap', _external=True)}",
        ]
    )
    body = "\n".join(parts)
    resp = Response(body, mimetype="text/plain")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp

# Explore routes → app.routes.explore blueprint

@bp.get("/sitemap.xml")
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

    _add(url_for("jobs.jobs", _external=True), priority="1.0", changefreq="daily")
    _add(url_for("jobs.landing", _external=True), priority="0.95", changefreq="weekly")
    _add(url_for("payments.pricing", _external=True), priority="0.75", changefreq="weekly")
    _add(url_for("jobs.developers", _external=True), priority="0.65", changefreq="monthly")
    _add(url_for("browse.companies", _external=True), priority="0.8", changefreq="weekly")
    _add(url_for("browse.explore_hub", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("browse.explore_remote", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("browse.explore_functions", _external=True), priority="0.7", changefreq="weekly")

    # Top company profile pages
    try:
        _top_companies = Job.company_list(limit=50)
        for _tc in _top_companies:
            _cn = _tc.get("company_name") or ""
            _cs = _slugify(_cn)
            if _cs:
                _add(url_for("browse.company_detail_page", slug=_cs, _external=True),
                     priority="0.6", changefreq="weekly")
    except Exception as _exc:
        logger.debug("sitemap company entries failed: %s", _exc)
    _add(url_for("jobs.about", _external=True), priority="0.8", changefreq="monthly")
    _add(url_for("carl.resources", _external=True), priority="0.9", changefreq="weekly")
    _add(url_for("carl.market_research_index", _external=True), priority="0.9", changefreq="weekly")
    for _r in REPORTS:
        _add(url_for("carl.market_research_report", slug=_r["slug"], _external=True), priority="0.85", changefreq="monthly")
    _add(url_for("jobs.recruiter_salary_board", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("salary.salary_tool", _external=True), priority="0.85", changefreq="weekly")
    _add(url_for("salary.salary_by_title", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("salary.salary_top_companies", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("salary.salary_underpaid", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("salary.salary_compare_cities", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("salary.salary_by_function", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("salary.salary_trends", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("salary.compensation_methodology", _external=True), priority="0.6", changefreq="monthly")
    _add(url_for("auth.hire", _external=True), priority="0.8", changefreq="monthly")
    _add(url_for("payments.post_a_job", _external=True), priority="0.75", changefreq="monthly")
    _add(url_for("auth.docs_api", _external=True), priority="0.6", changefreq="monthly")
    _add(url_for("jobs.legal", _external=True), priority="0.2", changefreq="yearly")
    _add(url_for("jobs.tracker", _external=True), priority="0.6", changefreq="weekly")
    _add(url_for("insights.career_evaluate", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("insights.career_ai_exposure", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("insights.career_hiring_trends", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("insights.career_earnings", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("insights.career_paths", _external=True), priority="0.7", changefreq="weekly")
    _add(url_for("insights.career_market_position", _external=True), priority="0.7", changefreq="weekly")

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
        loc = url_for("jobs.jobs", title=target.get("title"), country=target.get("country"), _external=True)
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
                jloc = url_for("jobs.job_detail", job_id=canonical_id, _external=True)
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
@bp.get("/jobs/<path:job_id>")
def job_detail(job_id: str):
    """Render a dedicated page for a single job listing."""
    # Extract numeric ID prefix (slug may follow after the first hyphen)
    m = re.match(r"^(\d+)", job_id)
    numeric_id = m.group(1) if m else job_id
    row = Job.get_by_id(numeric_id)
    if not row:
        abort(404)

    title = re.sub(r"\s+", " ", (row.get("job_title") or "(Untitled)").strip())
    # Redirect bare /jobs/<id> to canonical /jobs/<id>-<slug> (301 permanent)
    slug = _slugify(title)
    canonical_id = f"{numeric_id}-{slug}" if slug else numeric_id
    if job_id != canonical_id:
        return redirect(url_for("jobs.job_detail", job_id=canonical_id), 301)
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
        "jobs/job_detail.html",
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
_static_img_dir = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "static", "img")
)

@bp.get("/favicon.ico")
def favicon_ico():
    return send_from_directory(_static_img_dir, "favicon.ico", mimetype="image/x-icon")

@bp.get("/apple-touch-icon.png")
@bp.get("/apple-touch-icon-precomposed.png")
def apple_touch_icon_well_known():
    return send_from_directory(
        _static_img_dir, "apple-touch-icon.png", mimetype="image/png"
    )

# ------------------------------------------------------------------
# Service worker (must be served from root scope)
# ------------------------------------------------------------------
@bp.get("/sw.js")
def service_worker():
    """Render the PWA service worker with ASSET_VERSION injected so cache busts on deploy."""
    asset_version = current_app.config.get("ASSET_VERSION", "v1")
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
@bp.get("/about")
def about():
    """Render the About Catalitium page."""
    return render_template("site/about.html")

# Companies routes → app.routes.companies blueprint

@bp.get("/developers")
def developers():
    """Simple, human-facing overview of the v1 JSON API."""
    return render_template(
        "site/developers.html",
    )

# ------------------------------------------------------------------
# API key + v1 routes + summary → app.routes.api_v1 blueprint

# ------------------------------------------------------------------
# Tracker (wire orphaned template)
# ------------------------------------------------------------------
@bp.get("/tracker")
def tracker():
    """Render the job application tracker page."""
    return render_template("jobs/tracker.html")


# ------------------------------------------------------------------
# Browse: explore + companies (second blueprint; url_for("browse.*") unchanged)
# ------------------------------------------------------------------

browse_bp = Blueprint("browse", __name__)


@browse_bp.get("/explore")
def explore_hub():
    """Render the Explore Hub with top titles, locations, and companies."""
    try:
        data = get_explore_data()
    except Exception:
        logger.exception("explore_hub data fetch failed")
        data = {"top_titles": [], "top_locations": [], "top_companies": []}
    return render_template(
        "jobs/explore.html",
        top_titles=data.get("top_titles", []),
        top_locations=data.get("top_locations", []),
        top_companies=data.get("top_companies", []),
    )


@browse_bp.get("/explore/remote-companies")
def explore_remote():
    """Render the remote-friendliness leaderboard."""
    try:
        companies = get_remote_companies(limit=50)
    except Exception:
        logger.exception("explore_remote data fetch failed")
        companies = []
    return render_template("jobs/explore_remote.html", companies=companies)


@browse_bp.get("/explore/functions")
def explore_functions():
    """Render the function category browser."""
    try:
        functions = get_function_distribution()
    except Exception:
        logger.exception("explore_functions data fetch failed")
        functions = []
    return render_template("jobs/explore_functions.html", functions=functions)


@browse_bp.get("/companies")
def companies():
    """Render the DB-driven company discovery hub."""
    search = (request.args.get("search") or "").strip()
    page, per_page = resolve_pagination(default_per_page=24)
    offset = (page - 1) * per_page

    try:
        total = Job.company_count(search=search or None)
        rows = Job.company_list(search=search or None, limit=per_page, offset=offset)
    except Exception:
        total = 0
        rows = []

    companies_data = []
    for r in rows:
        name = r.get("company_name") or ""
        countries_raw = r.get("countries") or []
        countries = sorted(set(c for c in countries_raw if c and c.strip()))
        job_count = r.get("job_count", 0)
        salary_count = r.get("salary_count", 0)
        latest = r.get("latest_date")
        latest_str = ""
        if latest:
            latest_str = format_job_date_string(str(latest).strip())
        companies_data.append({
            "slug": _slugify(name),
            "name": name,
            "job_count": job_count,
            "locations": countries[:8],
            "has_salary_data": salary_count > 0,
            "salary_pct": round(100 * salary_count / job_count) if job_count else 0,
            "latest_posting_date": latest_str,
        })

    pages_display = max(1, (total + per_page - 1) // per_page) if total else 1
    pagination = {
        "page": page,
        "pages": pages_display,
        "total": total,
        "per_page": per_page,
        "has_prev": page > 1,
        "has_next": page < pages_display,
        "prev_url": url_for("browse.companies", search=search or None, page=page - 1)
        if page > 1 else None,
        "next_url": url_for("browse.companies", search=search or None, page=page + 1)
        if page < pages_display else None,
    }

    return render_template(
        "jobs/companies.html",
        companies=companies_data,
        search_q=search,
        pagination=pagination,
    )


@browse_bp.get("/companies/<slug>")
def company_detail_page(slug: str):
    """Render an individual company profile page."""
    slug = (slug or "").strip().lower()
    if not slug:
        abort(404)

    company_name = Job.company_name_by_slug(slug, slugify_fn=_slugify)
    if not company_name:
        abort(404)

    detail = Job.company_detail(company_name)
    if not detail:
        abort(404)

    job_count = detail.get("job_count", 0)
    countries_raw = detail.get("countries") or []
    countries = sorted(set(c for c in countries_raw if c and c.strip()))
    titles_raw = detail.get("titles_norm") or []
    salary_count = detail.get("salary_count", 0)
    latest = detail.get("latest_date")
    latest_str = format_job_date_string(str(latest).strip()) if latest else ""

    from collections import Counter as _Counter

    title_counts = _Counter(t.strip().title() for t in titles_raw if t and t.strip())
    title_distribution = sorted(title_counts.items(), key=lambda x: (-x[1], x[0]))[:20]

    salary_pct = round(100 * salary_count / job_count) if job_count else 0

    job_rows = Job.company_jobs(company_name, limit=50)
    jobs_display = []
    for row in job_rows:
        r_title = re.sub(r"\s+", " ", (row.get("job_title") or "").strip())
        r_loc = row.get("location") or "Remote / Anywhere"
        r_date = row.get("date")
        r_date_str = format_job_date_string(str(r_date).strip()) if r_date else ""
        is_new = _job_is_new(r_date, r_date)
        is_ghost = _job_is_ghost(r_date)
        salary_range = row.get("job_salary_range") or ""

        estimated_display = None
        median_currency = None
        sal_min = sal_max = None
        try:
            rec = get_salary_for_location(r_loc)
            if rec:
                median, currency = rec[0], rec[1]
                median_currency = currency
                estimated_display, sal_min, sal_max = estimate_salary_display(r_title, median)
        except Exception:
            pass

        jobs_display.append({
            "id": row.get("id"),
            "title": r_title,
            "company": company_name,
            "location": r_loc,
            "description": parse_job_description(row.get("job_description") or ""),
            "date_posted": r_date_str,
            "date_raw": str(r_date).strip() if r_date else "",
            "link": row.get("link"),
            "is_new": is_new,
            "is_ghost": is_ghost,
            "salary_range": salary_range,
            "estimated_salary_range_compact": estimated_display,
            "median_salary_currency": median_currency,
            "salary_min": sal_min,
            "salary_max": sal_max,
        })

    company_data = {
        "name": company_name,
        "slug": slug,
        "job_count": job_count,
        "locations": countries,
        "title_distribution": title_distribution,
        "salary_pct": salary_pct,
        "has_salary_data": salary_count > 0,
        "latest_posting_date": latest_str,
    }

    return render_template(
        "jobs/company_detail.html",
        company=company_data,
        jobs=jobs_display,
    )
