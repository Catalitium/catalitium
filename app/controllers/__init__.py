"""Blueprint registration for Catalitium route modules."""

from .api import bp as api_bp
from .auth import bp as auth_bp
from .carl import bp as carl_bp, carl_business_bp, cv_builder_bp
from .jobs import bp as jobs_bp, browse_bp
from .payments import bp as payments_bp
from .salary import bp as salary_bp, insights_bp

ALL_BLUEPRINTS = (
    auth_bp,
    jobs_bp,
    carl_bp,
    carl_business_bp,
    cv_builder_bp,
    browse_bp,
    insights_bp,
    salary_bp,
    payments_bp,
    api_bp,
)

__all__ = [
    "ALL_BLUEPRINTS",
    "api_bp",
    "auth_bp",
    "browse_bp",
    "carl_bp",
    "carl_business_bp",
    "cv_builder_bp",
    "insights_bp",
    "jobs_bp",
    "payments_bp",
    "salary_bp",
]
