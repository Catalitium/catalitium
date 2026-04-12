"""Blueprint registration for Catalitium route modules."""

from .api_v1 import bp as api_v1_bp
from .career import bp as career_bp
from .companies import bp as companies_bp
from .explore import bp as explore_bp
from .salary import bp as salary_bp
from .stripe_routes import bp as stripe_bp

ALL_BLUEPRINTS = (
    explore_bp,
    career_bp,
    salary_bp,
    companies_bp,
    stripe_bp,
    api_v1_bp,
)
