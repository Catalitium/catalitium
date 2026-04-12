"""Job catalog domain: listings, taxonomy, explore hub, career tools.

Merged from former ``jobs``, ``taxonomy``, ``explore``, and ``career`` modules.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .db import get_db, logger, _pg_connect
from .money import get_salary_for_location, parse_salary_range_string
from ..normalization import COUNTRY_NORM, LOCATION_COUNTRY_HINTS, SWISS_LOCATION_TERMS

# =============================================================================
# TAXONOMY
# =============================================================================

FUNCTION_CATEGORIES: Dict[str, List[str]] = {
    "Backend": [
        "backend", "back-end", "back end", "server-side", "api engineer",
        "systems engineer", "golang", "java ", "python developer", "ruby",
        "software engineer", "software developer",
    ],
    "Frontend": [
        "frontend", "front-end", "front end", "react", "angular", "vue",
        "ui engineer", "ui developer", "css",
    ],
    "Fullstack": [
        "fullstack", "full-stack", "full stack",
    ],
    "ML/AI": [
        "machine learning", "ml ", "ml/", "ai ", "ai/",
        "artificial intelligence", "deep learning", "nlp",
        "computer vision", "llm",
    ],
    "Data": [
        "data engineer", "data scientist", "data analyst",
        "analytics engineer", "bi ", "business intelligence",
        "etl", "data platform", "dbt",
    ],
    "DevOps/Infra": [
        "devops", "sre", "site reliability", "infrastructure",
        "platform engineer", "cloud engineer", "kubernetes",
        "terraform", "aws engineer", "docker",
    ],
    "Security": [
        "security", "infosec", "cybersecurity", "appsec",
        "penetration", "soc",
    ],
    "Product": [
        "product manager", "product owner", "product lead",
        "product director", "scrum master", "agile",
    ],
    "Design": [
        "designer", "ux ", "ui/ux", "ux/ui", "design lead",
        "product design", "figma", "design system",
    ],
    "Management": [
        "engineering manager", "vp engineering", "cto",
        "head of engineering", "director of engineering",
        "tech lead manager", "vp engineer", "head of",
    ],
}

_CATEGORY_INDEX: List[Tuple[str, str]] = []
for _cat, _keywords in FUNCTION_CATEGORIES.items():
    for _kw in sorted(_keywords, key=len, reverse=True):
        _CATEGORY_INDEX.append((_kw, _cat))


def categorize_function(title_norm: str | None) -> str:
    """Map a normalized job title to a canonical function category.

    Returns one of the keys in ``FUNCTION_CATEGORIES`` or ``"Other"``.
    """
    if not title_norm:
        return "Other"
    t = title_norm.strip().lower()
    for keyword, category in _CATEGORY_INDEX:
        if keyword in t:
            return category
    return "Other"


_categorize_function = categorize_function  # legacy name used in tests / callers

# =============================================================================
# JOB LISTINGS & COMPANY AGGREGATES
# =============================================================================

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_job_date_string(s: str) -> str:
    """Normalize job date strings for display.
    - If 'YYYYMMDD' -> 'YYYY-MM-DD'
    - If 'YYYY-MM-DD' -> unchanged
    - ISO timestamps -> date portion only
    - Otherwise return original trimmed string
    """
    if not s:
        return ""
    s = str(s).strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo}-{d}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo}-{d}"
    iso_candidate = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_candidate)
        return dt.date().isoformat()
    except ValueError:
        pass
    prefix_match = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if prefix_match:
        return prefix_match.group(1)
    return s


def clean_job_description_text(text: str) -> str:
    """Clean description by removing leading relative-age prefixes and stray labels."""
    if not text:
        return ""
    t = str(text)
    t = re.sub(r"^\s*\W*\d{8}\s*\n?", "", t)
    t = re.sub(r"^\s*\d+\s*(minutes?|hours?|days?|weeks?)\s+ago\s+[^\w\s]\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*Details\s*\n+", "", t, flags=re.IGNORECASE)
    return t.strip()


# ---------------------------------------------------------------------------
# Job summary cache
# ---------------------------------------------------------------------------

def get_job_summary(job_id: int) -> Optional[Dict]:
    """Return cached AI summary for job_id, or None if not yet generated."""
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                "SELECT bullets, skills FROM job_summaries WHERE job_id = %s",
                [job_id],
            )
            row = cur.fetchone()
            if row:
                return {"bullets": list(row[0] or []), "skills": list(row[1] or [])}
    except Exception as exc:
        logger.debug("get_job_summary error: %s", exc)
    return None


def save_job_summary(job_id: int, bullets: list, skills: list) -> None:
    """Upsert AI summary for job_id into the cache table."""
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO job_summaries (job_id, bullets, skills, created_at)
                VALUES (%s, %s::jsonb, %s::jsonb, NOW())
                ON CONFLICT (job_id) DO UPDATE
                  SET bullets    = EXCLUDED.bullets,
                      skills     = EXCLUDED.skills,
                      created_at = NOW()
                """,
                [job_id, json.dumps(bullets), json.dumps(skills)],
            )
    except Exception as exc:
        logger.warning("save_job_summary error: %s", exc)


# ---------------------------------------------------------------------------
# Job class
# ---------------------------------------------------------------------------

class Job:
    table = "jobs"
    _EU_CODES: Set[str] = {
        "AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE",
        "IT","LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE"
    }
    _EU_FILTER_CODES: Set[str] = set(_EU_CODES)
    _CACHE_TTL = 120  # seconds
    _CACHE_MAX = 128
    _cache_count: Dict[Tuple, Tuple[float, int]] = {}
    _cache_search: Dict[Tuple, Tuple[float, List[Dict]]] = {}

    @staticmethod
    def _cache_prune(target: Dict):
        if len(target) <= Job._CACHE_MAX:
            return
        oldest = sorted(target.items(), key=lambda kv: kv[1][0])[: len(target) - Job._CACHE_MAX]
        for key, _ in oldest:
            target.pop(key, None)

    @staticmethod
    def _cache_get_count(key: Tuple) -> Optional[int]:
        now = time.time()
        hit = Job._cache_count.get(key)
        if hit and now - hit[0] < Job._CACHE_TTL:
            return hit[1]
        return None

    @staticmethod
    def _cache_set_count(key: Tuple, value: int) -> None:
        Job._cache_count[key] = (time.time(), int(value))
        Job._cache_prune(Job._cache_count)

    @staticmethod
    def _cache_get_search(key: Tuple) -> Optional[List[Dict]]:
        now = time.time()
        hit = Job._cache_search.get(key)
        if hit and now - hit[0] < Job._CACHE_TTL:
            return hit[1]
        return None

    @staticmethod
    def _cache_set_search(key: Tuple, value: List[Dict]) -> None:
        Job._cache_search[key] = (time.time(), value)
        Job._cache_prune(Job._cache_search)

    @staticmethod
    def _normalize_title(value: Optional[str]) -> str:
        return (value or "").strip().lower()

    @staticmethod
    def _escape_like(value: str) -> str:
        value = value.replace("\\", "\\\\")
        value = value.replace("%", r"\%")
        value = value.replace("_", r"\_")
        return value

    @staticmethod
    def _country_patterns(codes: Iterable[str]) -> Tuple[List[str], List[str]]:
        seps_before = [" ", "(", ",", "/", "-"]
        seps_after = [" ", ")", ",", "/", "-"]
        patterns: List[str] = []
        equals: Set[str] = set()
        seen_like: Set[str] = set()

        def add_like(pattern: str) -> None:
            if pattern not in seen_like:
                patterns.append(pattern)
                seen_like.add(pattern)

        normalized_codes = {code.upper() for code in codes if code}
        for code in normalized_codes:
            if code == "IN":
                equals.update({"in", "india"})
                india_aliases = {
                    "india","bharat","bangalore","bengaluru","mumbai","pune","delhi","new delhi",
                    "gurgaon","gurugram","noida","hyderabad","chennai","kolkata","ahmedabad"
                }
                for alias in india_aliases:
                    add_like(f"%{Job._escape_like(alias)}%")
                continue

            token = Job._escape_like(code.lower())
            equals.add(code.lower())
            for before in seps_before:
                for after in seps_after:
                    add_like(f"%{before}{token}{after}%")
                add_like(f"%{before}{token}")
            if len(code) > 2:
                add_like(f"%{token}%")

        if "EU" in normalized_codes:
            add_like(f"%{Job._escape_like('eu')}%")

        aliases: Set[str] = set()
        for alias, mapped in COUNTRY_NORM.items():
            if mapped.upper() in normalized_codes and len(alias) > 2:
                aliases.add(alias.lower())
        for alias in sorted(aliases):
            add_like(f"%{Job._escape_like(alias)}%")

        for hint, mapped in LOCATION_COUNTRY_HINTS.items():
            if mapped.upper() in normalized_codes:
                add_like(f"%{Job._escape_like(hint)}%")
                if len(hint) <= 3:
                    equals.add(hint)

        return patterns, sorted(equals)

    @staticmethod
    def count(
        title: Optional[str] = None,
        country: Optional[str] = None,
        salary_min: Optional[int] = None,
        **filter_kw,
    ) -> int:
        """Return number of jobs matching optional filters."""
        key = ((title or "").strip().lower(), (country or "").strip().lower(), salary_min or 0)
        if not filter_kw:
            cached = Job._cache_get_count(key)
            if cached is not None:
                return cached
        where_sql, params_pg = Job._where(title, country, salary_min=salary_min, **filter_kw)
        db = get_db()
        with db.cursor() as cur:
            cur.execute(f"SELECT COUNT(1) FROM jobs {where_sql}", params_pg)
            row = cur.fetchone()
            value = int(row[0] if row else 0)
            if not filter_kw:
                Job._cache_set_count(key, value)
            return value

    @staticmethod
    def search(
        title: Optional[str] = None,
        country: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        salary_min: Optional[int] = None,
        **filter_kw,
    ) -> List[Dict]:
        """Return matching jobs ordered by recency."""
        key = (
            (title or "").strip().lower(),
            (country or "").strip().lower(),
            int(limit),
            int(offset),
            salary_min or 0,
        )
        if not filter_kw:
            cached = Job._cache_get_search(key)
            if cached is not None:
                return cached
        where_sql, params_pg = Job._where(title, country, salary_min=salary_min, **filter_kw)
        db = get_db()
        params = list(params_pg)
        sql = f"""
            SELECT
                id,
                job_title,
                job_title_norm,
                company_name,
                job_description,
                location,
                city,
                region,
                country,
                link,
                date,
                COALESCE(salary, '') AS job_salary_range
            FROM jobs {where_sql}
            {Job._order_by(country)}
            LIMIT %s OFFSET %s
        """
        params.extend([int(limit), int(offset)])
        with db.cursor() as cur:
            cur.execute(sql, params)
            cols = [desc[0] for desc in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            if not filter_kw:
                Job._cache_set_search(key, rows)
            return rows

    @staticmethod
    def insert_many(rows: List[Dict]) -> int:
        """Bulk insert jobs, ignoring duplicates by link."""
        if not rows:
            return 0
        cols = [
            "job_id", "job_title", "job_title_norm", "normalized_job",
            "company_name", "job_description", "location", "city", "region",
            "country", "geo_id", "robot_code", "link", "salary", "date",
        ]
        placeholders = ", ".join(["%s"] * len(cols))
        sql = f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT (link) DO NOTHING"

        payload = []
        for row in rows:
            title = row.get("job_title") or row.get("title") or ""
            job_id = (
                row.get("job_id") or row.get("jobId") or row.get("id")
                or row.get("external_id") or row.get("externalId")
            )
            job_title_norm = Job._normalize_title(row.get("job_title_norm") or title)
            normalized_job = row.get("normalized_job") or job_title_norm
            company_name = (
                row.get("company_name") or row.get("company") or row.get("employer")
                or row.get("job_company") or ""
            )
            location = row.get("location") or row.get("job_location") or ""
            city = row.get("city") or ""
            region = row.get("region") or ""
            country = row.get("country") or row.get("country_code") or ""
            geo_id = row.get("geo_id") or row.get("geo") or ""
            robot_code = row.get("robot_code") or row.get("robotCode") or row.get("robot") or 0
            try:
                robot_code_int = int(robot_code)
            except Exception:
                robot_code_int = 0
            link = row.get("link") or row.get("job_link") or row.get("url") or ""
            salary = row.get("salary") or row.get("compensation") or ""
            date_value = (
                row.get("date") or row.get("job_date") or row.get("date_posted")
                or row.get("posted_at") or ""
            )
            payload.append((
                job_id, title, job_title_norm, normalized_job, company_name,
                row.get("job_description") or row.get("description") or "",
                location, city, region, country, geo_id, robot_code_int,
                link, salary, date_value,
            ))

        db = None
        close_after = False
        try:
            try:
                db = get_db()
            except RuntimeError:
                db = _pg_connect()
                close_after = True
            with db.cursor() as cur:
                cur.executemany(sql, payload)
                return cur.rowcount or 0
        finally:
            if close_after and db:
                try:
                    db.close()
                except Exception:
                    pass

    @staticmethod
    def get_by_id(job_id: str) -> Optional[Dict]:
        """Return a single job row by primary key id."""
        try:
            pk = int(str(job_id).strip())
        except (TypeError, ValueError):
            return None
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute(
                    """SELECT id, job_title, company_name, job_description,
                              location, city, region, country, link, date,
                              COALESCE(salary, '') AS job_salary_range
                       FROM jobs WHERE id = %s LIMIT 1""",
                    [pk],
                )
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
                return dict(zip(cols, row)) if row else None
        except Exception as exc:
            logger.warning("Job.get_by_id(%s) failed: %s", pk, exc)
            return None

    @staticmethod
    def get_link(job_id: Optional[str]) -> Optional[str]:
        """Return the outbound link for a job id if available."""
        if job_id is None:
            return None
        value = str(job_id).strip()
        if not value:
            return None
        try:
            value_param = int(value)
        except (TypeError, ValueError):
            return None

        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT link FROM jobs WHERE id = %s", [value_param])
            row = cur.fetchone()
        if not row:
            return None

        link = None
        try:
            if isinstance(row, dict):
                link = row.get("link")
            elif hasattr(row, "keys"):
                link = row["link"]
            elif hasattr(row, "link"):
                link = row.link
            elif hasattr(row, "__getitem__"):
                link = row[0]
        except Exception:
            link = None
        return link.strip() if isinstance(link, str) else None

    @staticmethod
    def _where(
        title: Optional[str],
        country: Optional[str],
        salary_min: Optional[int] = None,
        *,
        remote: bool = False,
        has_salary: bool = False,
        freshness: Optional[int] = None,
        function_cat: Optional[str] = None,
        salary_max: Optional[int] = None,
    ) -> Tuple[str, Tuple]:
        clauses_pg: List[str] = []
        params_pg: List = []

        if title:
            t_norm = Job._normalize_title(title)
            if t_norm:
                tokens = [tok for tok in t_norm.split() if tok]
                specials = {"remote", "developer"}
                remote_flag = "remote" in tokens
                developer_flag = "developer" in tokens
                core_tokens = [tok for tok in tokens if tok not in specials]
                core_query = " ".join(core_tokens).strip()

                if core_query:
                    like = f"%{Job._escape_like(core_query)}%"
                    clause_pg = "(job_title_norm ILIKE %s ESCAPE '\\' OR LOWER(job_title) LIKE %s ESCAPE '\\')"
                    clauses_pg.append(clause_pg)
                    params_pg.extend([like, like])

                if remote_flag:
                    remote_like = f"%{Job._escape_like('remote')}%"
                    clause_pg_remote = "(job_title_norm ILIKE %s ESCAPE '\\' OR LOWER(job_title) LIKE %s ESCAPE '\\' OR LOWER(location) LIKE %s ESCAPE '\\')"
                    clauses_pg.append(clause_pg_remote)
                    params_pg.extend([remote_like, remote_like, remote_like])

                if developer_flag:
                    dev_terms = ["developer", "programmer", "coder", "software developer", "software engineer"]
                    patterns = [f"%{Job._escape_like(term)}%" for term in dev_terms]
                    clause_pg_terms: List[str] = []
                    for _ in dev_terms:
                        clause_pg_terms.extend([
                            "job_title_norm ILIKE %s ESCAPE '\\'",
                            "LOWER(job_title) LIKE %s ESCAPE '\\'",
                        ])
                    clause_pg_dev = "(" + " OR ".join(clause_pg_terms) + ")"
                    clauses_pg.append(clause_pg_dev)
                    for pattern in patterns:
                        params_pg.extend([pattern, pattern])

        if country:
            c_raw = (country or "").strip().lower()
            if c_raw:
                upper = c_raw.upper()
                code = upper if len(upper) == 2 and upper.isalpha() else None

                eu_hubs = ["madrid", "paris", "berlin", "barcelona", "milan", "milano"]
                india_hubs = [
                    "bangalore", "bengaluru", "mumbai", "pune", "delhi", "new delhi",
                    "gurgaon", "gurugram", "noida", "hyderabad", "chennai", "kolkata", "ahmedabad",
                ]

                subclauses_pg: List[str] = []
                columns_to_search = ("location", "city", "region", "country")

                if upper == "UK":
                    stop_terms = ("tukums", "latvia")
                    block_pg: List[str] = []
                    for term in stop_terms:
                        pattern = f"%{Job._escape_like(term)}%"
                        for column in ("location", "city", "region"):
                            block_pg.append(f"LOWER(COALESCE({column}, '')) NOT LIKE %s ESCAPE '\\'")
                            params_pg.append(pattern)
                    if block_pg:
                        clauses_pg.append("(" + " AND ".join(block_pg) + ")")

                if upper == "HIGH_PAY":
                    high_pay_cities = ["san francisco", "new york", "zurich", "berlin", "paris", "madrid", "london"]
                    placeholders_pg = ", ".join(["%s"] * len(high_pay_cities))
                    city_clause_pg = f"LOWER(COALESCE(city, '')) IN ({placeholders_pg})"
                    params_pg.extend([c.lower() for c in high_pay_cities])
                    subclauses_pg.append(city_clause_pg)
                elif upper == "EU":
                    eu_codes = sorted(Job._EU_FILTER_CODES)
                    placeholders_pg = ", ".join(["%s"] * len(eu_codes))
                    country_clause_pg = f"LOWER(COALESCE(country, '')) IN ({placeholders_pg})"
                    params_pg.extend([c.lower() for c in eu_codes])
                    subclauses_pg.append(country_clause_pg)

                    if eu_hubs:
                        hub_placeholders_pg = ", ".join(["%s"] * len(eu_hubs))
                        city_clause_pg = f"LOWER(COALESCE(city, '')) IN ({hub_placeholders_pg})"
                        params_pg.extend([h.lower() for h in eu_hubs])
                        subclauses_pg.append(city_clause_pg)
                elif code == "IN":
                    subclauses_pg.append("LOWER(COALESCE(country, '')) = %s")
                    params_pg.append("in")

                    hub_placeholders_pg = ", ".join(["%s"] * len(india_hubs))
                    city_clause_pg = f"LOWER(COALESCE(city, '')) IN ({hub_placeholders_pg})"
                    params_pg.extend([h.lower() for h in india_hubs])
                    subclauses_pg.append(city_clause_pg)
                elif upper == "CH":
                    swiss_like_pg: List[str] = []
                    for term in SWISS_LOCATION_TERMS:
                        pattern = f"%{Job._escape_like(term)}%"
                        swiss_like_pg.append("LOWER(COALESCE(location, '')) LIKE %s ESCAPE '\\'")
                        params_pg.append(pattern)
                    if swiss_like_pg:
                        subclauses_pg.append("(" + " OR ".join(swiss_like_pg) + ")")
                elif code:
                    patterns_like, equals_exact = Job._country_patterns({code})
                    if equals_exact:
                        eq_pg = []
                        for value in equals_exact:
                            value_lower = value.lower()
                            for column in columns_to_search:
                                eq_pg.append(f"LOWER(COALESCE({column}, '')) = %s")
                                params_pg.append(value_lower)
                        if eq_pg:
                            subclauses_pg.append("(" + " OR ".join(eq_pg) + ")")
                    if patterns_like:
                        like_pg = []
                        for pattern in patterns_like:
                            for column in columns_to_search:
                                like_pg.append(f"LOWER(COALESCE({column}, '')) LIKE %s ESCAPE '\\'")
                                params_pg.append(pattern)
                        if like_pg:
                            subclauses_pg.append("(" + " OR ".join(like_pg) + ")")
                else:
                    pattern = f"%{Job._escape_like(c_raw)}%"
                    like_pg = []
                    for column in columns_to_search:
                        like_pg.append(f"LOWER(COALESCE({column}, '')) LIKE %s ESCAPE '\\'")
                        params_pg.append(pattern)
                    if like_pg:
                        subclauses_pg.append("(" + " OR ".join(like_pg) + ")")

                if subclauses_pg:
                    clause_pg = "(" + " OR ".join(subclauses_pg) + ")"
                    clauses_pg.append(clause_pg)

        if salary_min and salary_min > 0:
            clauses_pg.append("job_salary >= %s")
            params_pg.append(salary_min)

        if remote:
            clauses_pg.append("(LOWER(COALESCE(location, '')) LIKE '%%remote%%')")

        if has_salary:
            clauses_pg.append("(salary IS NOT NULL AND salary != '')")

        if freshness and freshness in (7, 14, 30):
            clauses_pg.append("(date >= CURRENT_DATE - INTERVAL '%s days')" % int(freshness))

        if function_cat:
            keywords = FUNCTION_CATEGORIES.get(function_cat, [])
            if keywords:
                kw_clauses = []
                for kw in keywords:
                    kw_clauses.append(
                        "LOWER(COALESCE(job_title_norm, LOWER(job_title))) LIKE %s ESCAPE '\\'"
                    )
                    params_pg.append(f"%{Job._escape_like(kw)}%")
                clauses_pg.append("(" + " OR ".join(kw_clauses) + ")")

        if salary_max and salary_max > 0:
            clauses_pg.append("(job_salary > 0 AND job_salary <= %s)")
            params_pg.append(salary_max)

        where_pg = f"WHERE {' AND '.join(clauses_pg)}" if clauses_pg else ""
        return where_pg, tuple(params_pg)

    # ------------------------------------------------------------------
    # Company aggregation (read-only, from existing jobs table)
    # ------------------------------------------------------------------

    @staticmethod
    def company_list(search: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Return companies with >= 2 jobs, ordered by job count descending."""
        where = ""
        params: List = []
        if search:
            where = "WHERE company_name ILIKE %s ESCAPE '\\'"
            params.append(f"%{Job._escape_like(search.strip())}%")
        sql = f"""
            SELECT company_name,
                   COUNT(*) AS job_count,
                   array_agg(DISTINCT country) AS countries,
                   MAX(date) AS latest_date,
                   COUNT(CASE WHEN salary IS NOT NULL AND salary != '' THEN 1 END) AS salary_count
            FROM jobs
            {where}
            GROUP BY company_name
            HAVING COUNT(*) >= 2
            ORDER BY COUNT(*) DESC
            LIMIT %s OFFSET %s
        """
        params.extend([int(limit), int(offset)])
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as exc:
            logger.warning("Job.company_list failed: %s", exc)
            return []

    @staticmethod
    def company_count(search: Optional[str] = None) -> int:
        """Count distinct companies with >= 2 jobs."""
        where = ""
        params: List = []
        if search:
            where = "WHERE company_name ILIKE %s ESCAPE '\\'"
            params.append(f"%{Job._escape_like(search.strip())}%")
        sql = f"""
            SELECT COUNT(*) FROM (
                SELECT company_name FROM jobs {where}
                GROUP BY company_name HAVING COUNT(*) >= 2
            ) sub
        """
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return int(row[0]) if row else 0
        except Exception as exc:
            logger.warning("Job.company_count failed: %s", exc)
            return 0

    @staticmethod
    def company_name_by_slug(slug: str, slugify_fn=None) -> Optional[str]:
        """Reverse a slug to the original company_name, or None if not found.

        slugify_fn must be the same _slugify used in app.py to ensure consistency.
        """
        if not slug or not slugify_fn:
            return None
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT company_name FROM jobs "
                    "GROUP BY company_name HAVING COUNT(*) >= 2"
                )
                for row in cur.fetchall():
                    cn = row[0] if row else ""
                    if cn and slugify_fn(cn) == slug:
                        return cn
        except Exception as exc:
            logger.warning("Job.company_name_by_slug(%s) failed: %s", slug, exc)
        return None

    @staticmethod
    def company_detail(company_name: str) -> Optional[Dict]:
        """Return aggregated stats for a single company, or None if < 2 jobs."""
        if not company_name:
            return None
        sql = """
            SELECT company_name,
                   COUNT(*) AS job_count,
                   array_agg(DISTINCT country) AS countries,
                   array_agg(DISTINCT COALESCE(NULLIF(job_title_norm, ''), LOWER(job_title))) AS titles_norm,
                   MAX(date) AS latest_date,
                   COUNT(CASE WHEN salary IS NOT NULL AND salary != '' THEN 1 END) AS salary_count
            FROM jobs
            WHERE company_name = %s
            GROUP BY company_name
            HAVING COUNT(*) >= 2
        """
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute(sql, [company_name])
                row = cur.fetchone()
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))
        except Exception as exc:
            logger.warning("Job.company_detail(%s) failed: %s", company_name, exc)
            return None

    @staticmethod
    def company_jobs(company_name: str, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Return job rows for a specific company, ordered by recency."""
        sql = """
            SELECT id, job_title, job_title_norm, company_name,
                   job_description, location, city, region, country,
                   link, date, COALESCE(salary, '') AS job_salary_range
            FROM jobs
            WHERE company_name = %s
            ORDER BY (date IS NULL) ASC, date DESC, id DESC
            LIMIT %s OFFSET %s
        """
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute(sql, [company_name, int(limit), int(offset)])
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as exc:
            logger.warning("Job.company_jobs(%s) failed: %s", company_name, exc)
            return []

    @staticmethod
    def _order_by(country: Optional[str]) -> str:
        if not country:
            return "ORDER BY (date IS NULL) ASC, date DESC, id DESC"
        code = country.strip().upper()
        if code == "EU":
            return (
                "ORDER BY CASE "
                "WHEN LOWER(location) LIKE '%%madrid%%' THEN 0 "
                "WHEN LOWER(location) LIKE '%%paris%%' THEN 1 "
                "WHEN LOWER(location) LIKE '%%berlin%%' THEN 2 "
                "WHEN LOWER(location) LIKE '%%barcelona%%' THEN 3 "
                "WHEN LOWER(location) LIKE '%%milan%%' THEN 4 "
                "WHEN LOWER(location) LIKE '%%milano%%' THEN 5 "
                "ELSE 6 END, "
                "(date IS NULL) ASC, date DESC, id DESC"
            )
        if code == "HIGH_PAY":
            return (
                "ORDER BY CASE "
                "WHEN LOWER(location) LIKE '%%san francisco%%' THEN 0 "
                "WHEN LOWER(location) LIKE '%%new york%%' THEN 1 "
                "WHEN LOWER(location) LIKE '%%zurich%%' THEN 2 "
                "WHEN LOWER(location) LIKE '%%berlin%%' THEN 3 "
                "WHEN LOWER(location) LIKE '%%paris%%' THEN 4 "
                "WHEN LOWER(location) LIKE '%%madrid%%' THEN 5 "
                "WHEN LOWER(location) LIKE '%%london%%' THEN 6 "
                "ELSE 7 END, "
                "(date IS NULL) ASC, date DESC, id DESC"
            )
        return "ORDER BY (date IS NULL) ASC, date DESC, id DESC"


# =============================================================================
# EXPLORE HUB
# =============================================================================

# ---------------------------------------------------------------------------
# In-memory LRU cache (same pattern as jobs.py)
# ---------------------------------------------------------------------------

_CACHE_TTL = 300  # 5 minutes for expensive aggregation queries
_CACHE_MAX = 64
_cache: Dict[tuple, tuple] = {}


def _cache_get(key: tuple):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    return None


def _cache_set(key: tuple, value):
    _cache[key] = (time.time(), value)
    if len(_cache) > _CACHE_MAX:
        oldest = sorted(_cache.items(), key=lambda kv: kv[1][0])[: len(_cache) - _CACHE_MAX]
        for k, _ in oldest:
            _cache.pop(k, None)


# ---------------------------------------------------------------------------
# Quality score
# ---------------------------------------------------------------------------

def compute_quality_score(job_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Return a QualityScore dict (see AGENT_CONTRACT.md).

    Scoring breakdown (max 100):
      - has salary text         → +25
      - description > 200 chars → +25
      - specific location (city) → +20
      - posted within 30 days   → +15
      - company name present    → +15
    """
    breakdown: Dict[str, int] = {
        "salary": 0,
        "description": 0,
        "location": 0,
        "freshness": 0,
        "company": 0,
    }

    salary_text = job_dict.get("salary") or job_dict.get("job_salary_range") or ""
    if isinstance(salary_text, str) and salary_text.strip():
        breakdown["salary"] = 25
    elif isinstance(salary_text, (int, float)) and salary_text > 0:
        breakdown["salary"] = 25

    desc = job_dict.get("job_description") or job_dict.get("description") or ""
    if len(str(desc)) > 200:
        breakdown["description"] = 25

    city = job_dict.get("city") or ""
    if isinstance(city, str) and city.strip():
        breakdown["location"] = 20

    date_val = job_dict.get("date") or job_dict.get("date_raw") or ""
    if date_val:
        try:
            if hasattr(date_val, "date"):
                dt = date_val
            else:
                cleaned = str(date_val).strip()
                if re.match(r"^\d{8}$", cleaned):
                    cleaned = f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
                dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if hasattr(dt, "tzinfo") and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if (now - dt).days <= 30:
                breakdown["freshness"] = 15
        except (ValueError, TypeError, OverflowError):
            pass

    company = job_dict.get("company_name") or job_dict.get("company") or ""
    if isinstance(company, str) and company.strip():
        breakdown["company"] = 15

    total = min(100, max(0, sum(breakdown.values())))
    return {"total": total, "breakdown": breakdown}


# ---------------------------------------------------------------------------
# Hiring urgency
# ---------------------------------------------------------------------------

def get_hiring_urgency(company_name: str) -> bool:
    """True if company has 5+ jobs posted in the last 14 days."""
    if not company_name:
        return False
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FROM jobs
                   WHERE company_name = %s
                     AND date >= CURRENT_DATE - INTERVAL '14 days'""",
                [company_name],
            )
            row = cur.fetchone()
            return (row[0] if row else 0) >= 5
    except Exception as exc:
        logger.debug("get_hiring_urgency(%s) error: %s", company_name, exc)
        return False


# ---------------------------------------------------------------------------
# Explore Hub aggregations
# ---------------------------------------------------------------------------

def get_explore_data() -> Dict[str, Any]:
    """Return top titles, locations, and companies for the Explore Hub."""
    cache_key = ("explore_data",)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    result: Dict[str, Any] = {
        "top_titles": [],
        "top_locations": [],
        "top_companies": [],
    }
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(NULLIF(job_title_norm, ''), LOWER(job_title)) AS title_key,
                       COUNT(*) AS cnt,
                       MIN(CASE WHEN salary IS NOT NULL AND salary != '' THEN salary END) AS sample_salary
                FROM jobs
                GROUP BY title_key
                ORDER BY cnt DESC
                LIMIT 20
            """)
            cols = [d[0] for d in cur.description]
            result["top_titles"] = [
                {"name": r[0], "job_count": r[1], "salary_sample": r[2]}
                for r in cur.fetchall()
            ]

            cur.execute("""
                SELECT COALESCE(NULLIF(country, ''), 'Unknown') AS loc,
                       COUNT(*) AS cnt,
                       MIN(CASE WHEN salary IS NOT NULL AND salary != '' THEN salary END) AS sample_salary
                FROM jobs
                GROUP BY loc
                ORDER BY cnt DESC
                LIMIT 20
            """)
            result["top_locations"] = [
                {"name": r[0], "job_count": r[1], "salary_sample": r[2]}
                for r in cur.fetchall()
            ]

            cur.execute("""
                SELECT company_name,
                       COUNT(*) AS cnt,
                       MIN(CASE WHEN salary IS NOT NULL AND salary != '' THEN salary END) AS sample_salary
                FROM jobs
                WHERE company_name IS NOT NULL AND company_name != ''
                GROUP BY company_name
                ORDER BY cnt DESC
                LIMIT 20
            """)
            result["top_companies"] = [
                {"name": r[0], "job_count": r[1], "salary_sample": r[2]}
                for r in cur.fetchall()
            ]
    except Exception as exc:
        logger.warning("get_explore_data failed: %s", exc)

    _cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Remote-friendliness ranking
# ---------------------------------------------------------------------------

def get_remote_companies(limit: int = 50) -> List[Dict[str, Any]]:
    """Return companies ranked by % of remote job postings."""
    cache_key = ("remote_companies", limit)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("""
                SELECT company_name,
                       COUNT(*) AS total_jobs,
                       COUNT(CASE WHEN LOWER(COALESCE(location, '')) LIKE '%%remote%%' THEN 1 END) AS remote_jobs,
                       MAX(date) AS latest_date
                FROM jobs
                WHERE company_name IS NOT NULL AND company_name != ''
                GROUP BY company_name
                HAVING COUNT(*) >= 2
                   AND COUNT(CASE WHEN LOWER(COALESCE(location, '')) LIKE '%%remote%%' THEN 1 END) > 0
                ORDER BY COUNT(CASE WHEN LOWER(COALESCE(location, '')) LIKE '%%remote%%' THEN 1 END)::float
                         / COUNT(*)::float DESC,
                         COUNT(*) DESC
                LIMIT %s
            """, [int(limit)])
            rows = []
            for r in cur.fetchall():
                total = r[1] or 1
                remote = r[2] or 0
                rows.append({
                    "company_name": r[0],
                    "total_jobs": total,
                    "remote_jobs": remote,
                    "remote_pct": round(remote / total * 100, 1),
                    "latest_date": str(r[3]) if r[3] else "",
                })
            _cache_set(cache_key, rows)
            return rows
    except Exception as exc:
        logger.warning("get_remote_companies failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Function distribution
# ---------------------------------------------------------------------------

def get_function_distribution(location: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return job counts per function category with % having salary data."""
    cache_key = ("fn_distribution", (location or "").lower())
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        db = get_db()
        params: list = []
        where = ""
        if location:
            where = "WHERE LOWER(COALESCE(country, '')) = %s"
            params.append(location.strip().lower())
        with db.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(NULLIF(job_title_norm, ''), LOWER(job_title)) AS title_key,
                       salary
                FROM jobs {where}
            """, params)
            cat_counts: Counter[str] = Counter()
            cat_salary: Counter[str] = Counter()
            for row in cur.fetchall():
                cat = categorize_function(row[0])
                cat_counts[cat] += 1
                if row[1] and str(row[1]).strip():
                    cat_salary[cat] += 1
            result = []
            for cat in sorted(cat_counts, key=cat_counts.get, reverse=True):  # type: ignore[arg-type]
                total = cat_counts[cat]
                with_sal = cat_salary.get(cat, 0)
                result.append({
                    "function": cat,
                    "job_count": total,
                    "has_salary_pct": round(with_sal / total * 100, 1) if total else 0,
                })
            _cache_set(cache_key, result)
            return result
    except Exception as exc:
        logger.warning("get_function_distribution failed: %s", exc)
        return []


# =============================================================================
# CAREER INTELLIGENCE
# =============================================================================

# ── AI keyword list (lazy-compiled on first access) ──────────────────────
_AI_KEYWORDS = [
    "artificial intelligence", "machine learning", "deep learning",
    "neural network", "llm", "gpt", "nlp", "computer vision",
    "generative ai", "ai agent", "automation", "copilot", "chatbot",
]
_AI_PATTERN: Optional[re.Pattern] = None


def _ensure_ai_pattern() -> re.Pattern:
    global _AI_PATTERN
    if _AI_PATTERN is None:
        _AI_PATTERN = re.compile(
            "|".join(re.escape(kw) for kw in _AI_KEYWORDS), re.IGNORECASE
        )
    return _AI_PATTERN

# ── Title progression maps ───────────────────────────────────────────────
_IC_LADDER = ["junior", "mid", "senior", "staff", "principal", "distinguished"]
_MGMT_LADDER = ["lead", "manager", "director", "vp", "head"]


def _level_index(title_lower: str) -> Tuple[int, str]:
    """Return (index, track) for a title on the IC or mgmt ladder."""
    for i, level in enumerate(_IC_LADDER):
        if level in title_lower:
            return i, "ic"
    for i, level in enumerate(_MGMT_LADDER):
        if level in title_lower:
            return i, "mgmt"
    return 1, "ic"


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════


def compute_worth_it_score(
    job_dict: Dict[str, Any],
    salary_ref: Optional[Tuple],
    company_stats: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Score a job 0-100 across five dimensions (each 0-20).

    Returns a WorthItScore dict with ``total`` and ``breakdown``.
    """
    breakdown: Dict[str, int] = {}

    job_salary_str = job_dict.get("job_salary_range") or job_dict.get("salary") or ""
    job_salary_val = job_dict.get("job_salary") or parse_salary_range_string(str(job_salary_str))
    has_salary = job_salary_val is not None and job_salary_val
    median = float(salary_ref[0]) if salary_ref else None
    if has_salary and median:
        breakdown["salary_vs_market"] = 20 if float(job_salary_val) >= median else 10
    elif has_salary:
        breakdown["salary_vs_market"] = 10
    elif median:
        breakdown["salary_vs_market"] = 5
    else:
        breakdown["salary_vs_market"] = 0

    job_count = int(company_stats.get("job_count", 0)) if company_stats else 0
    latest_date_raw = (company_stats.get("latest_date") or "") if company_stats else ""
    recent_post = False
    if latest_date_raw:
        try:
            if isinstance(latest_date_raw, datetime):
                ld = latest_date_raw
            elif hasattr(latest_date_raw, "isoformat"):
                ld = datetime.fromisoformat(latest_date_raw.isoformat())
            else:
                ld = datetime.fromisoformat(str(latest_date_raw).replace("Z", "+00:00"))
            if ld.tzinfo is None:
                ld = ld.replace(tzinfo=timezone.utc)
            recent_post = (datetime.now(timezone.utc) - ld) <= timedelta(days=14)
        except Exception:
            pass
    if job_count >= 10 and recent_post:
        breakdown["company_signal"] = 20
    elif job_count >= 5:
        breakdown["company_signal"] = 10
    elif job_count >= 2:
        breakdown["company_signal"] = 5
    else:
        breakdown["company_signal"] = 0

    desc = job_dict.get("job_description") or job_dict.get("description") or ""
    location = job_dict.get("location") or ""
    rq = 0
    if len(desc) > 500:
        rq += 8
    elif len(desc) > 200:
        rq += 4
    if has_salary:
        rq += 6
    if location and location.lower() not in ("", "remote", "anywhere"):
        rq += 6
    breakdown["role_quality"] = min(rq, 20)

    loc_lower = location.lower()
    if "remote" in loc_lower:
        breakdown["remote_availability"] = 20
    elif "hybrid" in loc_lower:
        breakdown["remote_availability"] = 10
    else:
        breakdown["remote_availability"] = 0

    alt_count = job_dict.get("_alternatives_count", 0)
    if alt_count >= 10:
        breakdown["alternatives_count"] = 20
    elif alt_count >= 5:
        breakdown["alternatives_count"] = 10
    elif alt_count >= 2:
        breakdown["alternatives_count"] = 5
    else:
        breakdown["alternatives_count"] = 0

    total = sum(breakdown.values())
    return {"total": min(total, 100), "breakdown": breakdown}


def find_alternatives(
    title: str,
    location: str,
    exclude_id: Optional[int] = None,
    limit: int = 5,
) -> List[Dict]:
    """Search for similar jobs by title, excluding *exclude_id*."""
    try:
        country = ""
        if location:
            parts = [p.strip() for p in location.split(",")]
            if parts:
                country = parts[-1]
        results = Job.search(title=title, country=country, limit=limit + 5)
        filtered = [
            r for r in results
            if r.get("id") != exclude_id
        ]
        return filtered[:limit]
    except Exception as exc:
        logger.debug("find_alternatives failed: %s", exc)
        return []


def compute_ai_exposure(function_category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Rank function categories by AI-keyword prevalence in job descriptions.

    Returns a list of AIExposure dicts sorted by exposure_pct desc.
    """
    ai_pattern = _ensure_ai_pattern()
    try:
        db = get_db()
        with db.cursor() as cur:
            where = ""
            params: list = []
            if function_category:
                where = "WHERE LOWER(job_title_norm) LIKE %s ESCAPE '\\'"
                params.append(f"%{function_category.lower()}%")
            cur.execute(
                f"""
                SELECT
                    COALESCE(NULLIF(job_title_norm, ''), LOWER(job_title)) AS func,
                    job_description,
                    job_salary
                FROM jobs
                {where}
                """,
                params,
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.debug("compute_ai_exposure query failed: %s", exc)
        return []

    buckets: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        raw_title = (row[0] or "").strip().lower()
        desc = row[1] or ""
        salary_val = row[2]

        func_name = categorize_function(raw_title)
        if func_name not in buckets:
            buckets[func_name] = {"total": 0, "ai": 0, "salaries": []}
        buckets[func_name]["total"] += 1
        if ai_pattern.search(desc):
            buckets[func_name]["ai"] += 1
        if salary_val:
            buckets[func_name]["salaries"].append(float(salary_val))

    results = []
    for func_name, data in buckets.items():
        if data["total"] < 2:
            continue
        pct = (data["ai"] / data["total"]) * 100
        median_sal = None
        if data["salaries"]:
            sorted_s = sorted(data["salaries"])
            mid = len(sorted_s) // 2
            median_sal = sorted_s[mid] if len(sorted_s) % 2 else (sorted_s[mid - 1] + sorted_s[mid]) / 2
        cat = "ai-native" if pct > 50 else ("ai-adjacent" if pct >= 20 else "ai-distant")
        results.append({
            "function_name": func_name,
            "exposure_pct": round(pct, 1),
            "category": cat,
            "job_count": data["total"],
            "median_salary": median_sal,
        })
    results.sort(key=lambda x: -x["exposure_pct"])
    return results


def get_hiring_velocity(
    location: Optional[str] = None,
    function: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Compare per-company hiring in last 30 days vs previous 30 days."""
    try:
        db = get_db()
        with db.cursor() as cur:
            clauses = []
            params: list = []
            if location:
                clauses.append("LOWER(COALESCE(location,'')) LIKE %s ESCAPE '\\'")
                params.append(f"%{location.lower()}%")
            if function:
                clauses.append("LOWER(COALESCE(job_title_norm,'')) LIKE %s ESCAPE '\\'")
                params.append(f"%{function.lower()}%")
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            cur.execute(
                f"""
                SELECT
                    company_name,
                    COUNT(*) FILTER (WHERE date >= NOW() - INTERVAL '30 days') AS recent,
                    COUNT(*) FILTER (WHERE date >= NOW() - INTERVAL '60 days'
                                       AND date < NOW() - INTERVAL '30 days') AS previous,
                    COUNT(*) AS total
                FROM jobs
                {where}
                GROUP BY company_name
                HAVING COUNT(*) >= 2
                ORDER BY COUNT(*) FILTER (WHERE date >= NOW() - INTERVAL '30 days') DESC
                LIMIT %s
                """,
                params + [limit],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as exc:
        logger.debug("get_hiring_velocity query failed: %s", exc)
        return []

    results = []
    for row in rows:
        recent = int(row.get("recent") or 0)
        previous = int(row.get("previous") or 0)
        if previous > 0:
            velocity_pct = round(((recent - previous) / previous) * 100, 1)
        elif recent > 0:
            velocity_pct = 100.0
        else:
            velocity_pct = 0.0
        if velocity_pct > 20:
            trend = "growing"
        elif velocity_pct < -20:
            trend = "declining"
        else:
            trend = "stable"
        results.append({
            "company_name": row.get("company_name") or "",
            "recent_count": recent,
            "previous_count": previous,
            "velocity_pct": velocity_pct,
            "trend": trend,
            "total_jobs": int(row.get("total") or 0),
        })
    return results


def estimate_earnings(
    title: str,
    location: str,
    currency: str = "EUR",
) -> Dict[str, Any]:
    """Build a low/median/high salary estimate from reference + crowd submissions."""
    result: Dict[str, Any] = {
        "base_low": None,
        "base_median": None,
        "base_high": None,
        "currency": currency,
        "location": location,
        "title": title,
        "data_source": "insufficient",
    }

    ref_data = get_salary_for_location(location) if location else None
    ref_median = float(ref_data[0]) if ref_data else None
    ref_currency = ref_data[1] if ref_data else None

    sub_salaries: List[float] = []
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT base_salary FROM salary_submissions
                WHERE LOWER(job_title) LIKE %s ESCAPE '\\'
                  AND LOWER(location) LIKE %s ESCAPE '\\'
                """,
                (f"%{title.lower()}%", f"%{location.lower()}%"),
            )
            sub_salaries = [float(r[0]) for r in cur.fetchall() if r[0]]
    except Exception as exc:
        logger.debug("estimate_earnings submissions query failed: %s", exc)

    if ref_median and sub_salaries:
        all_points = sub_salaries + [ref_median]
        all_points.sort()
        n = len(all_points)
        median = all_points[n // 2]
        low = all_points[max(0, int(n * 0.25))]
        high = all_points[min(n - 1, int(n * 0.75))]
        result.update(
            base_low=int(low),
            base_median=int(median),
            base_high=int(high),
            currency=ref_currency or currency,
            data_source="combined",
        )
    elif ref_median:
        result.update(
            base_low=int(ref_median * 0.8),
            base_median=int(ref_median),
            base_high=int(ref_median * 1.2),
            currency=ref_currency or currency,
            data_source="reference",
        )
    elif sub_salaries:
        sub_salaries.sort()
        n = len(sub_salaries)
        median = sub_salaries[n // 2]
        low = sub_salaries[max(0, int(n * 0.25))]
        high = sub_salaries[min(n - 1, int(n * 0.75))]
        result.update(
            base_low=int(low),
            base_median=int(median),
            base_high=int(high),
            data_source="submissions",
        )

    return result


def get_career_paths(title_norm: str) -> Dict[str, Any]:
    """Derive progression, lateral moves, and top employers from jobs table."""
    title_lower = (title_norm or "").strip().lower()
    level_idx, track = _level_index(title_lower)

    base_function = re.sub(
        r"\b(junior|mid|senior|staff|principal|distinguished|lead|manager|director|vp|head)\b",
        "", title_lower,
    ).strip()
    base_function = re.sub(r"\s+", " ", base_function).strip()
    if not base_function:
        base_function = title_lower

    next_steps: List[Dict] = []
    lateral_moves: List[Dict] = []

    ic_next = _IC_LADDER[level_idx + 1:level_idx + 3] if level_idx + 1 < len(_IC_LADDER) else []
    for level in ic_next:
        search_term = f"{level} {base_function}"
        _add_path_node(search_term, next_steps)

    if track == "ic" and level_idx >= 2:
        for level in _MGMT_LADDER[:2]:
            search_term = f"{level} {base_function}"
            _add_path_node(search_term, next_steps)
    elif track == "mgmt":
        mgmt_next = _MGMT_LADDER[level_idx + 1:level_idx + 3] if level_idx + 1 < len(_MGMT_LADDER) else []
        for level in mgmt_next:
            search_term = f"{level} {base_function}"
            _add_path_node(search_term, next_steps)

    lateral_functions = _get_lateral_functions(base_function)
    current_level = _IC_LADDER[level_idx] if track == "ic" and level_idx < len(_IC_LADDER) else (
        _MGMT_LADDER[level_idx] if track == "mgmt" and level_idx < len(_MGMT_LADDER) else ""
    )
    for func in lateral_functions[:4]:
        search_term = f"{current_level} {func}" if current_level else func
        _add_path_node(search_term, lateral_moves)

    companies_hiring = _get_top_employers(title_lower)

    return {
        "current": title_norm,
        "next_steps": next_steps,
        "lateral_moves": lateral_moves,
        "companies_hiring": companies_hiring,
    }


def compute_market_position(
    title: str,
    location: str,
    years_exp: int,
    current_salary: float,
    currency: str = "EUR",
) -> Dict[str, Any]:
    """Return a SalaryPercentile-like dict for the user's position in the market."""
    ref_data = get_salary_for_location(location) if location else None
    ref_median = float(ref_data[0]) if ref_data else None

    all_salaries: List[float] = []
    if ref_median:
        all_salaries.append(ref_median)

    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT base_salary FROM salary_submissions
                WHERE LOWER(job_title) LIKE %s ESCAPE '\\'
                  AND LOWER(location) LIKE %s ESCAPE '\\'
                """,
                (f"%{title.lower()}%", f"%{location.lower()}%"),
            )
            for r in cur.fetchall():
                if r[0]:
                    all_salaries.append(float(r[0]))
    except Exception as exc:
        logger.debug("compute_market_position query failed: %s", exc)

    if not all_salaries:
        median = None
        percentile_rank = 50
        label = "insufficient_data"
    else:
        all_salaries.sort()
        n = len(all_salaries)
        median = all_salaries[n // 2]
        below = sum(1 for s in all_salaries if s < current_salary)
        percentile_rank = min(99, max(1, int((below / n) * 100)))
        if percentile_rank >= 65:
            label = "above_market"
        elif percentile_rank >= 35:
            label = "at_market"
        else:
            label = "below_market"

    exp_adjustment = max(0, (years_exp - 3)) * 1.5
    percentile_rank = min(99, int(percentile_rank + exp_adjustment))

    return {
        "title": title,
        "location": location,
        "user_salary": current_salary,
        "currency": currency,
        "median": median,
        "percentile_rank": percentile_rank,
        "label": label,
    }


# ═══════════════════════════════════════════════════════════════════════════
# PRIVATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _get_lateral_functions(base_function: str) -> List[str]:
    """Return a few lateral-move function names for a given base function."""
    laterals_map = {
        "engineer": ["data engineer", "devops engineer", "security engineer", "ml engineer"],
        "developer": ["data engineer", "devops engineer", "solutions architect"],
        "data": ["software engineer", "ml engineer", "product analyst"],
        "product": ["project manager", "program manager", "business analyst"],
        "design": ["product manager", "frontend developer", "ux researcher"],
        "marketing": ["product marketing", "growth analyst", "content strategist"],
        "analyst": ["data engineer", "product analyst", "business intelligence"],
    }
    for key, moves in laterals_map.items():
        if key in base_function:
            return moves
    return ["software engineer", "data analyst", "product manager"]


def _add_path_node(search_term: str, target_list: List[Dict]) -> None:
    """Query jobs for *search_term* and append a summary node to *target_list*."""
    try:
        results = Job.search(title=search_term, limit=50)
        if not results:
            return
        salaries = []
        for r in results:
            sal = r.get("job_salary") or parse_salary_range_string(r.get("job_salary_range") or "")
            if sal:
                salaries.append(float(sal))
        median_sal = None
        if salaries:
            salaries.sort()
            mid = len(salaries) // 2
            median_sal = salaries[mid]
        target_list.append({
            "title": search_term.title(),
            "median_salary": median_sal,
            "job_count": len(results),
        })
    except Exception as exc:
        logger.debug("_add_path_node(%s) failed: %s", search_term, exc)


def _get_top_employers(title_lower: str) -> List[Dict]:
    """Return companies with the most jobs matching *title_lower*."""
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT company_name, COUNT(*) AS cnt
                FROM jobs
                WHERE LOWER(COALESCE(job_title_norm, '')) LIKE %s ESCAPE '\\'
                GROUP BY company_name
                HAVING COUNT(*) >= 2
                ORDER BY cnt DESC
                LIMIT 10
                """,
                (f"%{title_lower}%",),
            )
            return [{"name": r[0], "count": r[1]} for r in cur.fetchall() if r[0]]
    except Exception as exc:
        logger.debug("_get_top_employers failed: %s", exc)
        return []
