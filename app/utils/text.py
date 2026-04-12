"""Text utility helpers for Catalitium."""

from app.factory import slugify as _slugify


def slugify_job_title(title: str) -> str:
    """Return a URL-safe slug from a job title string."""
    return _slugify(title or "")
