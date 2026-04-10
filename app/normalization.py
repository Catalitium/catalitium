"""Single source of truth for country and job-title normalization.

All city→country, alias→code, and title synonym mappings live here.
db.py and app.py both import from this module — never define these mappings elsewhere.
"""

import json
import re
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger("catalitium")


def _load_country_norm() -> Dict[str, str]:
    _path = Path(__file__).parent / "models" / "country_norm.json"
    try:
        with open(_path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("country_norm.json load failed: %s", exc)
        return {}


COUNTRY_NORM: Dict[str, str] = _load_country_norm()

LOCATION_COUNTRY_HINTS: Dict[str, str] = {
    "amsterdam": "NL",
    "atlanta": "US",
    "austin": "US",
    "barcelona": "ES",
    "belgium": "BE",
    "berlin": "DE",
    "berlin, de": "DE",
    "boston": "US",
    "brussels": "BE",
    "budapest": "HU",
    "charlotte": "US",
    "chicago": "US",
    "copenhagen": "DK",
    "dallas": "US",
    "denmark": "DK",
    "denver": "US",
    "dublin": "IE",
    "france": "FR",
    "frankfurt": "DE",
    "germany": "DE",
    "hamburg": "DE",
    "houston": "US",
    "italy": "IT",
    "lisbon": "PT",
    "london": "UK",
    "los angeles": "US",
    "los": "US",
    "madrid": "ES",
    "miami": "US",
    "milan": "IT",
    "minneapolis": "US",
    "munich": "DE",
    "netherlands": "NL",
    "new york": "US",
    "oslo": "NO",
    "paris": "FR",
    "philadelphia": "US",
    "phoenix": "US",
    "pittsburgh": "US",
    "portland": "US",
    "porto": "PT",
    "portugal": "PT",
    "prague": "CZ",
    "raleigh": "US",
    "salt lake city": "US",
    "salt": "US",
    "san francisco": "US",
    "seattle": "US",
    "spain": "ES",
    "stockholm": "SE",
    "switzerland": "CH",
    "tallinn": "EE",
    "uk": "UK",
    "vienna": "AT",
    "washington": "US",
    "zurich": "CH",
    # India hubs
    "bangalore": "IN",
    "bengaluru": "IN",
    "mumbai": "IN",
    "pune": "IN",
    "delhi": "IN",
    "new delhi": "IN",
    "gurgaon": "IN",
    "gurugram": "IN",
    "noida": "IN",
    "hyderabad": "IN",
    "chennai": "IN",
    "kolkata": "IN",
    "ahmedabad": "IN",
}

SWISS_LOCATION_TERMS = [
    "switzerland", "schweiz", "suisse", "svizzera", "swiss",
    "zurich", "geneva", "geneve", "lausanne", "lausane",
    "basel", "bern", "zug", "lucerne", "luzern",
    "winterthur", "ticino", "st gallen", "st. gallen",
]

TITLE_SYNONYMS: Dict[str, str] = {
    "swe": "software engineer", "software eng": "software engineer", "sw eng": "software engineer",
    "frontend": "front end", "front-end": "front end",
    "backend": "back end", "back-end": "back end",
    "fullstack": "full stack", "full-stack": "full stack",
    "pm": "product manager", "prod mgr": "product manager", "product owner": "product manager",
    "ds": "data scientist", "ml": "machine learning", "mle": "machine learning engineer",
    "sre": "site reliability engineer", "devops": "devops",
    "sec eng": "security engineer", "infosec": "security",
    "programmer": "developer", "coder": "developer",
}


def normalize_country(q: str) -> str:
    """Return normalized country code for a query string."""
    if not q:
        return ""
    t = q.strip().lower()
    if t in COUNTRY_NORM:
        return COUNTRY_NORM[t]
    if len(t) == 2 and t.isalpha():
        return t.upper()
    for token, code in COUNTRY_NORM.items():
        if re.search(rf"\b{re.escape(token)}\b", t):
            return code
    return q.strip()


def normalize_title(q: str) -> str:
    """Normalize a job title query string."""
    if not q:
        return ""
    s = q.lower()
    for k, v in TITLE_SYNONYMS.items():
        if k in s:
            s = s.replace(k, v)
    s = re.sub(r"[^\w\s\-\/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s
