"""Career decision intelligence routes (/career/ prefix)."""

from flask import Blueprint, render_template, request

from ..models.db import logger, get_salary_for_location, Job

bp = Blueprint("career", __name__)


@bp.get("/career/evaluate")
def career_evaluate():
    """'Is This Worth It?' evaluator for a specific job."""
    from ..models.career import compute_worth_it_score, find_alternatives

    job_id = request.args.get("job_id", "").strip()
    score = None
    job = None
    alternatives = []

    if job_id:
        try:
            job = Job.get_by_id(job_id)
        except Exception:
            job = None
        if job:
            salary_ref = get_salary_for_location(job.get("location") or "")
            company_stats = Job.company_detail(job.get("company_name") or "")
            title = job.get("job_title") or ""
            location = job.get("location") or ""
            alternatives = find_alternatives(title, location, exclude_id=job.get("id"))
            job["_alternatives_count"] = len(alternatives)
            score = compute_worth_it_score(job, salary_ref, company_stats)

    return render_template(
        "career_evaluate.html",
        job=job,
        score=score,
        alternatives=alternatives,
    )


@bp.get("/career/ai-exposure")
def career_ai_exposure():
    """AI/Automation exposure ranking by job function."""
    from ..models.career import compute_ai_exposure

    exposures = []
    try:
        exposures = compute_ai_exposure()
    except Exception as exc:
        logger.debug("career_ai_exposure failed: %s", exc)

    return render_template("career_ai_exposure.html", exposures=exposures)


@bp.get("/career/hiring-trends")
def career_hiring_trends():
    """Hiring velocity dashboard."""
    from ..models.career import get_hiring_velocity

    loc = request.args.get("location", "").strip() or None
    func = request.args.get("function", "").strip() or None
    velocity = []
    try:
        velocity = get_hiring_velocity(location=loc, function=func, limit=30)
    except Exception as exc:
        logger.debug("career_hiring_trends failed: %s", exc)

    return render_template("career_hiring_trends.html", velocity=velocity)


@bp.get("/career/earnings")
def career_earnings():
    """First-year earnings estimator."""
    from ..models.career import estimate_earnings

    title = request.args.get("title", "").strip()
    location = request.args.get("location", "").strip()
    current_salary_raw = request.args.get("current_salary", "").strip()
    currency = request.args.get("currency", "EUR").strip().upper()
    current_salary = None
    earnings = None

    if title and location:
        try:
            earnings = estimate_earnings(title, location, currency=currency)
        except Exception as exc:
            logger.debug("career_earnings failed: %s", exc)
        if current_salary_raw:
            try:
                current_salary = int(float(current_salary_raw))
            except (TypeError, ValueError):
                pass

    return render_template(
        "career_earnings.html",
        earnings=earnings,
        current_salary=current_salary,
    )


@bp.get("/career/paths")
def career_paths():
    """Career path explorer."""
    from ..models.career import get_career_paths

    title = request.args.get("title", "").strip()
    paths = None
    if title:
        try:
            paths = get_career_paths(title)
        except Exception as exc:
            logger.debug("career_paths failed: %s", exc)

    return render_template("career_paths.html", paths=paths)


@bp.get("/career/market-position")
def career_market_position():
    """Market position benchmarking tool."""
    from ..models.career import compute_market_position

    title = request.args.get("title", "").strip()
    location = request.args.get("location", "").strip()
    years_exp_raw = request.args.get("years_exp", "").strip()
    current_salary_raw = request.args.get("current_salary", "").strip()
    currency = request.args.get("currency", "EUR").strip().upper()
    position = None

    if title and location and years_exp_raw and current_salary_raw:
        try:
            years_exp = int(years_exp_raw)
            current_salary = float(current_salary_raw)
            position = compute_market_position(
                title, location, years_exp, current_salary, currency
            )
        except Exception as exc:
            logger.debug("career_market_position failed: %s", exc)

    return render_template("career_market_position.html", position=position)
