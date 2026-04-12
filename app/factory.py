"""Flask application factory and route definitions for Catalitium."""

import hashlib
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    Response,
    session,
    url_for,
)

from .config import PER_PAGE_MAX
from .models.db import SECRET_KEY, SUPABASE_URL, close_db, init_db, logger
from .utils import api_fail, coerce_datetime as _coerce_datetime, generate_request_id, slugify as _slugify
from werkzeug.middleware.proxy_fix import ProxyFix

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

ENVIRONMENT = os.getenv("FLASK_ENV") or os.getenv("ENV") or "production"


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

    if limiter is not None:
        for _ep, _rule in (
            ("carl.carl_analyze", "20 per minute"),
            ("carl.carl_chat", "40 per minute"),
            ("carl4b2b.carl4b2b_analyze", "20 per minute"),
            ("carl4b2b.carl4b2b_chat", "40 per minute"),
            ("auth.register", "10 per minute"),
            ("auth.auth_forgot_password", "5 per minute"),
            ("auth.auth_session_from_tokens", "30 per minute"),
            ("auth.account_delete", "5 per hour"),
            ("auth.profile", "10 per minute"),
            ("auth.hire_onboarding", "10 per minute"),
        ):
            _vf = app.view_functions.get(_ep)
            if _vf is not None:
                app.view_functions[_ep] = limiter.limit(_rule)(_vf)

        for _ep, _rule in (
            ("jobs.subscribe", "20 per minute"),
            ("jobs.contact", "12 per minute"),
            ("jobs.job_posting", "10 per minute"),
            ("jobs.api_autocomplete", "90 per minute"),
            ("jobs.api_share_search", "90 per minute"),
            ("jobs.api_salary_compare", "90 per minute"),
            ("jobs.studio_contact", "10 per minute"),
        ):
            _vf = app.view_functions.get(_ep)
            if _vf is not None:
                app.view_functions[_ep] = limiter.limit(_rule)(_vf)

        _jobs_list = app.view_functions.get("jobs.jobs")
        if _jobs_list is not None:
            app.view_functions["jobs.jobs"] = limiter.exempt(_jobs_list)

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

    # Macros imported with {% from ... import macro %} do not receive request context
    # unless imported "with context"; globals make csrf_token() work inside those macros.
    app.jinja_env.globals["csrf_token"] = _csrf_token

    def _api_request() -> bool:
        path = request.path or ""
        return path.startswith("/api/") or path.startswith("/v1/") or request.is_json

    def _wants_html() -> bool:
        """True when the client is likely a browser expecting HTML (not JSON API)."""
        if _api_request():
            return False
        accept = (request.headers.get("Accept") or "").lower()
        if "text/html" in accept:
            return True
        if request.accept_mimetypes.best_match(["text/html", "application/json"]) == "text/html":
            return True
        return False

    def _api_error(code: str, message: str, status: int = 400, details: Optional[Dict[str, Any]] = None):
        return jsonify(
            api_fail(
                code=code,
                message=message,
                request_id=getattr(g, "request_id", ""),
                details=details or {},
            )
        ), status

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
            "/post-job",
            "/docs/api",
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
        if _wants_html():
            return render_template("errors/404.html"), 404
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(500)
    def handle_server_error(error):
        logger.exception("Unhandled error", exc_info=error)
        if _api_request():
            return _api_error("internal_error", "Internal server error", 500)
        if _wants_html():
            return render_template("errors/500.html"), 500
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
        return redirect(request.referrer or url_for("jobs.jobs"))

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
        return url_for("jobs.job_detail", job_id=canonical_id, _external=_external)

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

    return app
