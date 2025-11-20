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
    parse_job_description,
    format_job_date_string,
    clean_job_description_text,
    insert_subscriber,
    insert_search_event,
    insert_subscribe_event,
    Job,
)
import random


BLACKLIST_LINKS = {
    "https://example.com/job/1",
}

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

    truthy_sqlite = {"1", "true", "on", "yes"}
    force_sqlite_env = os.getenv("FORCE_SQLITE")
    if not SUPABASE_URL:
        if force_sqlite_env is None or not force_sqlite_env.strip():
            os.environ["FORCE_SQLITE"] = "1"
            force_sqlite_env = "1"
        elif force_sqlite_env.strip().lower() not in truthy_sqlite:
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

    def _resolve_pagination(default_per_page: int = 20) -> Tuple[int, int]:
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

        if raw_title or raw_country:
            try:
                insert_search_event(
                    raw_title=raw_title,
                    raw_country=raw_country,
                    norm_title=title_q,
                    norm_country=q_country or "",
                    sal_floor=sal_floor,
                    sal_ceiling=sal_ceiling,
                    result_count=total,
                    page=max(1, page),
                    per_page=per_page,
                    source="web",
                )
            except Exception as exc:
                logger.warning("Failed to log search event: %s", exc)

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
            if median is not None:
                try:
                    from .models import db as _db_helpers
                    rng = _db_helpers.salary_range_around(median, pct=0.2)
                    if rng:
                        low_r, high_r, low_s, high_s = rng
                        median_compact = _db_helpers._compact_salary_number(median)
                        estimated_display = f"{low_s}\u2013{high_s}"
                        range_compact = (low_r, high_r)
                except Exception:
                    range_compact = None

            items.append(
                {
                    "id": row.get("id"),
                    "title": title,
                    "company": row.get("company_name") or "",
                    "location": loc,
                    "description": parse_job_description(row.get("job_description") or ""),
                    "date_posted": format_job_date_string(job_date_str) if job_date_str else "",
                    "link": link,
                    "is_new": _job_is_new(job_date_raw, row.get("date")),
                    "median_salary": int(median) if median is not None else None,
                    "median_salary_currency": currency,
                    "median_salary_compact": median_compact,
                    "estimated_salary_range_compact": estimated_display,
                    "estimated_salary_range_numeric": range_compact,
                }
            )

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

    @app.get("/api/jobs")
    def api_jobs():
        """Return jobs as JSON with pagination metadata."""
        raw_title = (request.args.get("title") or "").strip()
        raw_country = (request.args.get("country") or "").strip()
        page, per_page = _resolve_pagination()
        per_page_display = _display_per_page(per_page)

        cleaned_title, _, _ = parse_salary_query(raw_title)
        country_q = normalize_country(raw_country)
        title_q = normalize_title(cleaned_title)

        try:
            total = Job.count(title_q or None, country_q or None)
            offset = (max(1, page) - 1) * per_page
            rows = Job.search(title_q or None, country_q or None, limit=per_page, offset=offset)
        except Exception:
            total = 0
            rows = []

        items = []
        for row in rows:
            job_date_raw = row.get("date")
            job_date_str = str(job_date_raw).strip() if job_date_raw is not None else ""
            link = row.get("link")
            if link in BLACKLIST_LINKS:
                link = None
            items.append(
                {
                    "id": row.get("id"),
                    "title": _to_lc(row.get("job_title") or ""),
                    "description": clean_job_description_text(row.get("job_description") or ""),
                    "link": link,
                    "location": row.get("location"),
                    "job_date": format_job_date_string(job_date_str) if job_date_str else "",
                    "date": row.get("date"),
                    "is_new": _job_is_new(job_date_raw, row.get("date")),
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
        source = "api" if is_json else "form"
        if job_link:
            source = f"{source}_job"
        insert_subscribe_event(email=email, status=status, source=source, job_link=job_link)

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

        insert_search_event(
            raw_title=raw_title,
            raw_country=raw_country,
            norm_title=norm_title,
            norm_country=norm_country,
            sal_floor=None,
            sal_ceiling=None,
            result_count=0,
            page=0,
            per_page=0,
            source=source,
            event_type=event_type,
            event_status=status,
            job_id=job_id,
            job_title=job_title,
            job_company=job_company,
            job_location=job_location,
            job_link=job_link,
            job_summary=job_summary,
            email_hash=email_hash,
            meta=meta_dict or None,
        )
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

    return app


def _job_is_new(job_date_raw, row_date) -> bool:
    """Return True when the job was posted within the last two days."""
    dt = _coerce_datetime(row_date) or _coerce_datetime(job_date_raw)
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return (now - dt) <= timedelta(days=2)


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
