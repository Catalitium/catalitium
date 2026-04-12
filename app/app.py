"""Compatibility shim: ``create_app`` lives in ``app.factory``."""

from .factory import create_app, safe_parse_search_params
from .support.text_norm import slugify as _slugify

__all__ = ["create_app", "safe_parse_search_params", "_slugify"]
