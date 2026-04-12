"""Public model surface (prefer ``from app.models import Job, get_db`` in new code)."""

from .db import (
    Job,
    close_db,
    get_db,
    init_db,
    logger,
    parse_job_description,
    parse_salary_query,
    parse_salary_range_string,
    salary_range_around,
    SUPABASE_URL,
)

__all__ = [
    "Job",
    "SUPABASE_URL",
    "close_db",
    "get_db",
    "init_db",
    "logger",
    "parse_job_description",
    "parse_salary_query",
    "parse_salary_range_string",
    "salary_range_around",
]
