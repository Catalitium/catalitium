"""Salary routes: tools, contribution form, intelligence hub."""

import os
from datetime import timezone
from typing import Optional

from flask import Blueprint, redirect, render_template, request, url_for

from ..utils import (
    _SALARY_SEED,
    api_error_response,
    api_success_response,
    csrf_valid,
    get_salary_percentiles,
    parse_int_arg,
    parse_str_arg,
)
from ..models.db import logger
from ..models.money import get_salary_for_location, insert_salary_submission
from ..models.money import (
    compare_cities_salary,
    compute_percentile,
    get_function_benchmarks,
    get_ppp_indices,
    get_salary_trends,
)

bp = Blueprint("salary", __name__)

_EMAIL_RE = __import__("re").compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class _EmailNotValidError(ValueError):
    pass


def _validate_email(email: str):
    class _R:
        normalized: str
    r = _R()
    r.normalized = email.strip().lower()
    if not _EMAIL_RE.match(r.normalized):
        raise _EmailNotValidError(f"Invalid: {email!r}")
    return r


# ------------------------------------------------------------------
# Compensation methodology (static page)
# ------------------------------------------------------------------

@bp.get("/compensation/methodology")
def compensation_methodology():
    """Static page explaining how salary estimates and confidence scores work."""
    return render_template("compensation_methodology.html")


# ------------------------------------------------------------------
# Salary Tools: live DACH calculator + role/region report
# ------------------------------------------------------------------

@bp.get("/salary-tool")
@bp.get("/salary-report")
def salary_tool_redirect():
    return redirect(url_for("salary.salary_tool"), 301)


@bp.get("/salary-tools")
def salary_tool():
    import json as _json
    from datetime import datetime as _dt

    seed_json = _json.dumps(
        {f"{kw}:{city}": v for (kw, city), v in _SALARY_SEED.items()}
    )
    data = {
        "Software Engineering":   {"count": 12_400, "min":  88_000, "median": 130_000, "max": 175_000},
        "Product Management":     {"count":  3_200, "min":  85_000, "median": 125_000, "max": 165_000},
        "Data & ML":              {"count":  4_800, "min":  80_000, "median": 128_000, "max": 170_000},
        "Design":                 {"count":  1_800, "min":  72_000, "median": 108_000, "max": 140_000},
        "DevOps / SRE":           {"count":  2_200, "min":  90_000, "median": 132_000, "max": 170_000},
        "Engineering Management": {"count":  1_200, "min": 110_000, "median": 150_000, "max": 200_000},
    }
    region_data = {
        "Zurich": {"median": 130_000, "count": 8_400},
        "Geneva": {"median": 122_000, "count": 2_100},
        "Berlin": {"median":  82_000, "count": 6_800},
        "Munich": {"median":  90_000, "count": 3_200},
    }
    return render_template(
        "salary_report.html",
        data=data,
        region_data=region_data,
        generated=_dt.now(timezone.utc).strftime("%B %Y"),
        salary_seed_json=seed_json,
    )


@bp.get("/salary/by-title")
def salary_by_title():
    return render_template("salary_by_title.html")


@bp.get("/salary/top-companies")
def salary_top_companies():
    return render_template("salary_top_companies.html")


# ------------------------------------------------------------------
# Salary flywheel: crowd-sourced contribution form
# ------------------------------------------------------------------

@bp.get("/salary/contribute")
def salary_contribute():
    """Render the multi-step salary contribution form."""
    return render_template("salary_contribute.html")


@bp.post("/salary/contribute")
def salary_contribute_post():
    """Accept a salary submission; return percentile data."""
    if not csrf_valid():
        return api_error_response("invalid_csrf", "Session expired. Please refresh and try again.", 400)

    payload = request.get_json(silent=True) or {}
    job_title  = parse_str_arg(payload, "job_title",  max_len=120)
    company    = parse_str_arg(payload, "company",    max_len=120)
    location   = parse_str_arg(payload, "location",   max_len=80)
    seniority  = parse_str_arg(payload, "seniority",  max_len=40)
    currency   = parse_str_arg(payload, "currency",   max_len=3)
    email_raw  = parse_str_arg(payload, "email",      max_len=200)
    base_salary = parse_int_arg(payload, "base_salary", default=0, minimum=1, maximum=10_000_000)
    years_exp   = parse_int_arg(payload, "years_exp",   default=0, minimum=0, maximum=50)

    if not job_title or not location or not seniority or base_salary < 1:
        return api_error_response("missing_fields", "job_title, location, seniority, and base_salary are required.", 400)

    _VALID_CURRENCIES = {"CHF", "EUR"}
    currency = currency.upper() if currency.upper() in _VALID_CURRENCIES else "CHF"

    email: Optional[str] = None
    if email_raw:
        try:
            email = _validate_email(email_raw).normalized
        except Exception:
            pass

    status = insert_salary_submission(
        job_title=job_title,
        company=company,
        location=location,
        seniority=seniority,
        base_salary=base_salary,
        currency=currency,
        years_exp=years_exp,
        email=email,
    )
    if status != "ok":
        return api_error_response("save_failed", "Could not save salary submission.", 500)

    percentiles = get_salary_percentiles(job_title, location)
    return api_success_response({"percentiles": percentiles or {}}, code="ok", message="ok")


# ------------------------------------------------------------------
# Salary Intelligence Hub
# ------------------------------------------------------------------

@bp.get("/salary/am-i-underpaid")
def salary_underpaid():
    """Am I Underpaid? — salary percentile checker."""
    result = None
    title = request.args.get("title", "").strip()
    location = request.args.get("location", "").strip()
    salary_raw = request.args.get("salary", "").strip()
    currency = request.args.get("currency", "CHF").strip().upper()
    if title and location and salary_raw:
        try:
            user_salary = float(salary_raw)
            if user_salary > 0:
                result = compute_percentile(title, location, user_salary, currency)
        except (ValueError, TypeError):
            pass
    return render_template("salary_underpaid.html", result=result)


@bp.get("/salary/compare-cities")
def salary_compare_cities():
    """Cross-city salary comparison with PPP adjustment."""
    ppp = get_ppp_indices()
    ppp_cities = sorted(ppp.keys())
    title = request.args.get("title", "").strip()
    selected_cities = request.args.getlist("cities")
    selected_cities = [c for c in selected_cities if c in ppp][:4]
    results = None
    if title and selected_cities:
        results = compare_cities_salary(title, selected_cities)
    return render_template(
        "salary_compare_cities.html",
        ppp_cities=ppp_cities,
        selected_cities=selected_cities,
        results=results,
    )


@bp.get("/salary/by-function")
def salary_by_function():
    """Salary benchmarks aggregated by function/team category."""
    location_filter = request.args.get("location", "").strip() or None
    benchmarks = get_function_benchmarks(location=location_filter)
    return render_template(
        "salary_by_function.html",
        benchmarks=benchmarks,
        location_filter=location_filter,
    )


@bp.get("/salary/trends")
def salary_trends():
    """Monthly salary trend data."""
    _CATEGORIES = [
        "Backend", "Frontend", "Fullstack", "ML/AI", "Data",
        "DevOps/Infra", "Product", "Design", "Security", "Management",
    ]
    selected_category = request.args.get("category", "").strip() or None
    selected_city = request.args.get("city", "").strip() or None
    trends = get_salary_trends(
        title_category=selected_category,
        city=selected_city,
        months=12,
    )
    return render_template(
        "salary_trends.html",
        trends=trends,
        categories=_CATEGORIES,
        selected_category=selected_category,
        selected_city=selected_city,
    )
