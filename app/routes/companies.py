"""Company discovery routes: hub + detail page."""

import re

from flask import Blueprint, abort, redirect, render_template, request, url_for

from ..helpers import (
    BLACKLIST_LINKS,
    TITLE_BUCKET1_KEYWORDS,
    TITLE_BUCKET2_KEYWORDS,
    estimate_salary_display,
    job_is_ghost,
    job_is_new,
    resolve_pagination,
    slugify,
)
from ..models.db import (
    Job,
    _compact_salary_number,
    format_job_date_string,
    get_salary_for_location,
    logger,
    parse_job_description,
    salary_range_around,
)

bp = Blueprint("companies", __name__)


@bp.get("/companies")
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
            "slug": slugify(name),
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
        "prev_url": url_for("companies.companies", search=search or None, page=page - 1)
        if page > 1 else None,
        "next_url": url_for("companies.companies", search=search or None, page=page + 1)
        if page < pages_display else None,
    }

    return render_template(
        "companies.html",
        companies=companies_data,
        search_q=search,
        pagination=pagination,
    )


@bp.get("/companies/<slug>")
def company_detail_page(slug: str):
    """Render an individual company profile page."""
    slug = (slug or "").strip().lower()
    if not slug:
        abort(404)

    company_name = Job.company_name_by_slug(slug, slugify_fn=slugify)
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
        is_new = job_is_new(r_date, r_date)
        is_ghost = job_is_ghost(r_date)
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
        "company_detail.html",
        company=company_data,
        jobs=jobs_display,
    )
