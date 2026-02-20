"""Flask application entry point and route definitions for Catalitium."""

import os
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional, Dict

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
    Job,
)
import random


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

ENVIRONMENT = os.getenv("FLASK_ENV") or os.getenv("ENV") or "development"

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

def create_app() -> Flask:
    """Instantiate and configure the Flask application."""
    app = Flask(__name__, template_folder="views/templates")
    env = ENVIRONMENT or "production"

    if not SUPABASE_URL:
        logger.error("SUPABASE_URL (or DATABASE_URL) must be configured before starting the app.")
        raise SystemExit(1)

    app.config.update(
        SECRET_KEY=SECRET_KEY,
        TEMPLATES_AUTO_RELOAD=(env != "production"),
        PER_PAGE_MAX=PER_PAGE_MAX,
        SUPABASE_URL=SUPABASE_URL,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    app.teardown_appcontext(close_db)

    def _resolve_pagination(default_per_page: int = 12) -> Tuple[int, int]:
        """Return (page, per_page_limit) constrained to safe bounds."""
        per_page_raw = request.args.get("per_page", default=default_per_page, type=int) or default_per_page
        per_page = max(1, min(per_page_raw, int(app.config.get("PER_PAGE_MAX", 100))))
        page_raw = request.args.get("page", default=1, type=int) or 1
        page = max(1, page_raw)
        return page, per_page

    def _display_per_page(per_page: int) -> int:
        """Return the value surfaced in pagination metadata."""
        if per_page < 5:
            return per_page
        return max(per_page, 10)

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
            if path.startswith("/static/"):
                # 30d cache for versioned static files; adjust if assets aren't fingerprinted
                response.headers.setdefault("Cache-Control", "public, max-age=2592000, immutable")
            else:
                response.headers.setdefault("Cache-Control", "public, max-age=60")
        except Exception:
            pass
        return response

    if not SECRET_KEY or SECRET_KEY == "dev-insecure-change-me":
        logger.error("SECRET_KEY must be set via environment. Aborting.")
        raise SystemExit(1)

    try:
        with app.app_context():
            init_db()
    except Exception as exc:
        logger.warning("init_db failed: %s", exc)

    @app.errorhandler(404)
    def handle_not_found(_error):
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(500)
    def handle_server_error(error):
        logger.exception("Unhandled error", exc_info=error)
        return jsonify({"error": "internal error"}), 500

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

        return render_template(
            "index.html",
            results=items,
            count=total,
            title_q=title_q,
            country_q=display_country,
            pagination=pagination,
        )

    @app.get("/recruiter-salary-board")
    def recruiter_salary_board():
        """Surface the dedicated job browser experience."""
        job_api_url = url_for("api_jobs")
        return render_template(
            "job_browser.html",
            job_api=job_api_url,
        )

    @app.get("/api/jobs")
    def api_jobs():
        """Return jobs as JSON with pagination metadata.

        Uses the same title/country normalization as the main index route
        so the job browser and the homepage see the same Supabase jobs.
        """
        raw_title = (request.args.get("title") or "").strip()
        raw_country = (request.args.get("country") or "").strip()
        page, per_page = _resolve_pagination()
        per_page_display = _display_per_page(per_page)

        # Reuse the shared search param parsing to keep behavior consistent
        title_q, country_q, sal_floor, sal_ceiling = safe_parse_search_params(raw_title, raw_country)
        if raw_title and not title_q:
            title_q = normalize_title(raw_title)
        if raw_country and not country_q:
            country_q = normalize_country(raw_country)

        q_title = title_q or None
        q_country = country_q or None

        total: Optional[int]
        rows = []

        # First try: normal count+search. If COUNT is too heavy and times out,
        # fall back to search without relying on COUNT so we still show jobs.
        try:
            total = Job.count(q_title, q_country)
        except Exception:
            logger.exception("Job COUNT failed in api_jobs; falling back to search-only")
            total = None

        try:
            offset = (max(1, page) - 1) * per_page
            rows = Job.search(q_title, q_country, limit=per_page, offset=offset)
        except Exception:
            logger.exception("Job SEARCH failed in api_jobs")
            rows = []

        # If we have a title but no rows, relax the title filter once and try
        # a greedy country-only search so users still see something.
        if not rows and (q_title or raw_title):
            try:
                q_title = None
                offset = (max(1, page) - 1) * per_page
                rows = Job.search(q_title, q_country, limit=per_page, offset=offset)
                if total is None:
                    total = len(rows)
            except Exception:
                logger.exception("Fallback country-only search failed in api_jobs")

        if total is None:
            total = len(rows)

        items = []
        for row in rows:
            job_date_raw = row.get("date")
            job_date_str = str(job_date_raw).strip() if job_date_raw is not None else ""
            link = row.get("link")
            if link in BLACKLIST_LINKS:
                link = None
            title = (row.get("job_title") or "").strip()
            company = (row.get("company_name") or "").strip()
            location = row.get("location") or "Remote / Anywhere"
            description = clean_job_description_text(row.get("job_description") or "")
            
            # Format job_date as YYYY-MM-DD
            job_date_formatted = ""
            if job_date_raw:
                dt = _coerce_datetime(job_date_raw)
                if dt:
                    job_date_formatted = dt.date().isoformat()
            
            items.append(
                {
                    "id": row.get("id"),
                    "title": title,
                    "job_title": title,  # alias for compatibility
                    "job_company_name": company,
                    "company": company,  # alias
                    "description": description,
                    "job_description": description,  # alias
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

        return jsonify(
            {
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
        )

    @app.get("/api/jobs/summary")
    def api_jobs_summary():
        """Return summary statistics for jobs matching filters: count, median salary, remote share.

        Salary resolution order:
        - Prefer numeric job_salary from jobs table when available.
        - Fallback to parsing job_salary_range strings.
        - Finally, fallback to salary table via get_salary_for_location.
        """
        raw_title = (request.args.get("title") or "").strip()
        raw_country = (request.args.get("country") or "").strip()

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

        return jsonify(
            {
                "count": total,
                "salary": {
                    "median": int(median_salary) if median_salary is not None else None,
                    "currency": currency or None,
                },
                "remote_share": round(remote_share, 2),
            }
        )

    @app.post("/subscribe")
    def subscribe():
        """Handle newsletter subscriptions from form or JSON payloads."""
        is_json = request.is_json
        payload = request.get_json(silent=True) or {} if is_json else request.form
        email = (payload.get("email") or "").strip()
        job_id_raw = (payload.get("job_id") or "").strip()

        try:
            email = validate_email(email, check_deliverability=False).normalized
        except EmailNotValidError:
            if is_json:
                return jsonify({"error": "invalid_email"}), 400
            flash("Please enter a valid email.", "error")
            return redirect(url_for("index"))

        job_link = Job.get_link(job_id_raw)
        next_url = (payload.get("next") or "").strip()
        if not job_link and next_url:
            job_link = next_url
        status = insert_subscriber(email)

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
            message = "You're subscribed! You're all set."
            if is_json:
                body = {"status": "ok"}
                if job_link:
                    body["redirect"] = job_link
                return jsonify(body), 200
            flash(message, "success")
        elif status == "duplicate":
            if is_json:
                body = {"error": "duplicate"}
                if job_link:
                    body["redirect"] = job_link
                return jsonify(body), 200
            flash("You're already on the list.", "success")
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
    def subscribe_json():
        """Alias JSON endpoint for compatibility."""
        return subscribe()

    @app.post("/contact")
    def contact():
        """Handle contact form submissions (JSON or form)."""
        is_json = request.is_json
        payload = request.get_json(silent=True) or {} if is_json else request.form
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
    def contact_json():
        """Alias JSON endpoint for compatibility."""
        return contact()

    @app.post("/job-posting")
    def job_posting():
        """Handle anonymous job posting submissions (JSON or form)."""
        is_json = request.is_json
        payload = request.get_json(silent=True) or {} if is_json else request.form

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
    def job_posting_json():
        """Alias JSON endpoint for compatibility."""
        return job_posting()

    @app.post("/events/apply")
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
        raw_title = (request.args.get("title") or "").strip()
        raw_country = (request.args.get("country") or "").strip()
        title_q = normalize_title(raw_title)
        country_q = normalize_country(raw_country)
        rows = Job.search(title_q or None, country_q or None, limit=100, offset=0)
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
        return jsonify(
            {
                "count": len(items),
                "items": items,
                "meta": {"title": title_q, "country": country_q},
            }
        )

    @app.get("/api/autocomplete")
    def api_autocomplete():
        """Return distinct job title suggestions for autocomplete."""
        q = (request.args.get("q") or "").strip().lower()
        if len(q) < 2:
            return jsonify({"suggestions": []})
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
        return jsonify({"suggestions": suggestions})

    @app.get("/health")
    def health():
        """Expose a readiness probe indicating the database is reachable."""
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        except Exception:
            return jsonify({"status": "error", "db": "failed"}), 503
        return jsonify({"status": "ok", "db": "connected"}), 200

    @app.get("/legal")
    def legal():
        """Display combined privacy policy and terms information."""
        return render_template("legal.html")

    @app.get("/robots.txt")
    def robots_txt():
        """Expose robots.txt with sitemap reference."""
        body = "\n".join(
            [
                "User-agent: *",
                "Disallow:",
                f"Sitemap: {url_for('sitemap', _external=True)}",
            ]
        )
        return Response(body, mimetype="text/plain")

    @app.get("/sitemap.xml")
    def sitemap():
        """Generate a lightweight XML sitemap for primary surfaces."""
        today = datetime.utcnow().date().isoformat()
        urls = []

        def _add(loc: str, priority: str = "0.5", lastmod: str = today):
            if loc:
                urls.append({"loc": loc, "priority": priority, "lastmod": lastmod})

        _add(url_for("index", _external=True), priority="1.0")
        _add(url_for("legal", _external=True), priority="0.2")

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
            _add(loc, priority="0.7")

        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]
        for url in urls:
            xml_lines.append("  <url>")
            xml_lines.append(f"    <loc>{url['loc']}</loc>")
            xml_lines.append(f"    <lastmod>{url['lastmod']}</lastmod>")
            xml_lines.append(f"    <priority>{url['priority']}</priority>")
            xml_lines.append("  </url>")
        xml_lines.append("</urlset>")
        return Response("\n".join(xml_lines), mimetype="application/xml")

    # ------------------------------------------------------------------
    # Individual job detail page
    # ------------------------------------------------------------------
    @app.get("/jobs/<job_id>")
    def job_detail(job_id: str):
        """Render a dedicated page for a single job listing."""
        row = Job.get_by_id(job_id)
        if not row:
            return jsonify({"error": "not found"}), 404

        title = re.sub(r"\s+", " ", (row.get("job_title") or "(Untitled)").strip())
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
                if str(r.get("id")) != str(job_id) and len(related) < 3:
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
            "id": job_id,
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
        return render_template("job_detail.html", job=job, related=related)

    # ------------------------------------------------------------------
    # Market trends API
    # ------------------------------------------------------------------
    @app.get("/api/trends")
    def api_trends():
        """Return weekly job posting counts for the last 8 weeks by category."""
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute("""
                    WITH parsed AS (
                        SELECT
                            job_title,
                            location,
                            date::date AS parsed_date
                        FROM jobs
                        WHERE date IS NOT NULL
                    )
                    SELECT
                        DATE_TRUNC('week', parsed_date)::date AS week_start,
                        COUNT(*) AS total,
                        COUNT(CASE WHEN LOWER(job_title) LIKE '%ai%'
                                     OR LOWER(job_title) LIKE '%machine learning%'
                                     OR LOWER(job_title) LIKE '%ml engineer%' THEN 1 END) AS ai,
                        COUNT(CASE WHEN LOWER(job_title) LIKE '%developer%'
                                     OR LOWER(job_title) LIKE '%engineer%' THEN 1 END) AS dev,
                        COUNT(CASE WHEN LOWER(job_title) LIKE '%senior%' THEN 1 END) AS senior,
                        COUNT(CASE WHEN LOWER(location) LIKE '%remote%' THEN 1 END) AS remote
                    FROM parsed
                    WHERE parsed_date IS NOT NULL
                      AND parsed_date >= CURRENT_DATE - INTERVAL '8 weeks'
                    GROUP BY week_start
                    ORDER BY week_start ASC
                """)
                cols = [d[0] for d in cur.description]
                weeks = []
                for row in cur.fetchall():
                    d = dict(zip(cols, row))
                    ws = d.get("week_start")
                    label = ws.strftime("%b %d") if hasattr(ws, "strftime") else str(ws)[:10]
                    weeks.append({
                        "week": label,
                        "total": int(d.get("total") or 0),
                        "ai": int(d.get("ai") or 0),
                        "dev": int(d.get("dev") or 0),
                        "senior": int(d.get("senior") or 0),
                        "remote": int(d.get("remote") or 0),
                    })
        except Exception:
            logger.exception("Trends query failed")
            weeks = []
        return jsonify({"weeks": weeks})

    # ------------------------------------------------------------------
    # Salary report (printable HTML)
    # ------------------------------------------------------------------
    @app.get("/salary-report")
    def salary_report():
        """Render a printable salary insights report."""
        categories = [
            ("AI / ML", "ai"),
            ("Developer", "developer"),
            ("Senior", "senior"),
            ("Remote", "remote"),
            ("Data", "data"),
        ]
        regions = ["US", "EU", "UK", "CH"]
        data = {}
        for label, keyword in categories:
            rows = Job.search(normalize_title(keyword), None, limit=200, offset=0)
            salaries = []
            for r in rows:
                sal_str = r.get("job_salary_range") or ""
                if sal_str:
                    parsed = parse_salary_range_string(sal_str)
                    if parsed:
                        salaries.append(parsed)
                else:
                    rec = get_salary_for_location(r.get("location") or "")
                    if rec and rec[0]:
                        salaries.append(rec[0])
            if salaries:
                salaries.sort()
                n = len(salaries)
                med = salaries[n // 2] if n % 2 != 0 else (salaries[n // 2 - 1] + salaries[n // 2]) / 2
                data[label] = {"count": len(rows), "median": int(med), "min": int(salaries[0]), "max": int(salaries[-1])}
            else:
                data[label] = {"count": len(rows), "median": None, "min": None, "max": None}

        region_data = {}
        for region in regions:
            rows = Job.search(None, normalize_country(region), limit=200, offset=0)
            salaries = []
            for r in rows:
                rec = get_salary_for_location(r.get("location") or "")
                if rec and rec[0]:
                    salaries.append(rec[0])
            if salaries:
                salaries.sort()
                n = len(salaries)
                med = salaries[n // 2] if n % 2 != 0 else (salaries[n // 2 - 1] + salaries[n // 2]) / 2
                region_data[region] = {"count": len(rows), "median": int(med)}
            else:
                region_data[region] = {"count": len(rows), "median": None}

        generated = datetime.now(timezone.utc).strftime("%B %Y")
        return render_template("salary_report.html", data=data, region_data=region_data, generated=generated)

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
    application.run(debug=True)
