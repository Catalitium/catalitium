"""Public model surface — import domain symbols from their owning modules."""

from .catalog import FUNCTION_CATEGORIES, Job, categorize_function
from .cv import CVExtractionError, ExtractedCV, extract_cv_from_upload, normalize_cv_text
from .db import close_db, get_db, init_db, logger, parse_job_description, SUPABASE_URL
from .identity import (
    check_and_increment_api_key,
    confirm_api_key_by_token,
    create_api_key,
    get_api_key_by_email,
    get_stripe_order,
    get_subscription_by_stripe_id,
    get_user_subscriptions,
    insert_contact,
    insert_job_posting,
    insert_stripe_order,
    insert_subscriber,
    mark_stripe_order_job_submitted,
    mark_stripe_order_paid,
    revoke_api_key,
    sync_api_key_quota_for_api_access,
    upsert_user_subscription,
)
from .money import parse_salary_query, parse_salary_range_string, salary_range_around

__all__ = [
    # catalog
    "FUNCTION_CATEGORIES",
    "Job",
    "categorize_function",
    # cv
    "CVExtractionError",
    "ExtractedCV",
    "extract_cv_from_upload",
    "normalize_cv_text",
    # db
    "close_db",
    "get_db",
    "init_db",
    "logger",
    "parse_job_description",
    "SUPABASE_URL",
    # identity
    "check_and_increment_api_key",
    "confirm_api_key_by_token",
    "create_api_key",
    "get_api_key_by_email",
    "get_stripe_order",
    "get_subscription_by_stripe_id",
    "get_user_subscriptions",
    "insert_contact",
    "insert_job_posting",
    "insert_stripe_order",
    "insert_subscriber",
    "mark_stripe_order_job_submitted",
    "mark_stripe_order_paid",
    "revoke_api_key",
    "sync_api_key_quota_for_api_access",
    "upsert_user_subscription",
    # money
    "parse_salary_query",
    "parse_salary_range_string",
    "salary_range_around",
]
