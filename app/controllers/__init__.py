"""Blueprint registration for Catalitium route modules."""

from .api import bp as api_bp
from .browse import bp as browse_bp
from .carl import bp as carl_bp
from .insights import bp as insights_bp
from .payments import bp as payments_bp
from .salary import bp as salary_bp

ALL_BLUEPRINTS = (
    browse_bp,
    insights_bp,
    salary_bp,
    payments_bp,
    api_bp,
    carl_bp,
)
