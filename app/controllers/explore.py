"""Explore routes: hub, remote companies, function distribution."""

from flask import Blueprint, render_template

from ..models.db import logger
from ..models.explore import (
    get_explore_data,
    get_function_distribution,
    get_remote_companies,
)

bp = Blueprint("explore", __name__)


@bp.get("/explore")
def explore_hub():
    """Render the Explore Hub with top titles, locations, and companies."""
    try:
        data = get_explore_data()
    except Exception:
        logger.exception("explore_hub data fetch failed")
        data = {"top_titles": [], "top_locations": [], "top_companies": []}
    return render_template(
        "explore.html",
        top_titles=data.get("top_titles", []),
        top_locations=data.get("top_locations", []),
        top_companies=data.get("top_companies", []),
    )


@bp.get("/explore/remote-companies")
def explore_remote():
    """Render the remote-friendliness leaderboard."""
    try:
        companies = get_remote_companies(limit=50)
    except Exception:
        logger.exception("explore_remote data fetch failed")
        companies = []
    return render_template("explore_remote.html", companies=companies)


@bp.get("/explore/functions")
def explore_functions():
    """Render the function category browser."""
    try:
        functions = get_function_distribution()
    except Exception:
        logger.exception("explore_functions data fetch failed")
        functions = []
    return render_template("explore_functions.html", functions=functions)
