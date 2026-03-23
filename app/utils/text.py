"""Text utility helpers for Catalitium."""

from app.app import _slugify


def slugify_job_title(title: str) -> str:
    """Return a URL-safe slug from a job title string."""
    return _slugify(title or "")
