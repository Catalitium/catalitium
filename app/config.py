"""Central configuration constants for Catalitium.

All magic numbers and tunable thresholds live here.
Import from this module rather than scattering literals across the codebase.
"""

# ---------------------------------------------------------------------------
# Job search
# ---------------------------------------------------------------------------
PER_PAGE_MAX: int = 100      # Hard cap on results per request (also enforced in DB layer)
GHOST_JOB_DAYS: int = 30     # Jobs older than this are flagged as potentially filled

# ---------------------------------------------------------------------------
# Guest access
# ---------------------------------------------------------------------------
GUEST_DAILY_LIMIT: int = 5_000  # Max job views per day for unauthenticated users

# ---------------------------------------------------------------------------
# In-memory TTL cache settings (used in create_app)
# ---------------------------------------------------------------------------
SUMMARY_CACHE_TTL: int = 90         # seconds
SUMMARY_CACHE_MAX: int = 400

AUTOCOMPLETE_CACHE_TTL: int = 120
AUTOCOMPLETE_CACHE_MAX: int = 400

SALARY_INSIGHTS_CACHE_TTL: int = 120
SALARY_INSIGHTS_CACHE_MAX: int = 250

SITEMAP_CACHE_TTL: int = 3600       # sitemap.xml in-process cache + Cache-Control (seconds)

# ---------------------------------------------------------------------------
# Database pool
# ---------------------------------------------------------------------------
DB_POOL_MIN: int = 1
DB_POOL_MAX_DEFAULT: int = 4        # overridden by DB_POOL_MAX env var
