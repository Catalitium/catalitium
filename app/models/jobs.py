"""Job model: search, retrieval, bulk insert, summary cache, formatting helpers.

The Job class owns all SQL against the jobs table.
get_job_summary / save_job_summary own the job_summaries cache table.
format_job_date_string and clean_job_description_text are pure utilities
that live here because they operate exclusively on job data.
"""

import json
import re
import time
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .db import get_db, logger, _pg_connect
from ..normalization import COUNTRY_NORM, LOCATION_COUNTRY_HINTS, SWISS_LOCATION_TERMS


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
            db.commit()
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
    def count(title: Optional[str] = None, country: Optional[str] = None, salary_min: Optional[int] = None) -> int:
        """Return number of jobs matching optional filters."""
        key = ((title or "").strip().lower(), (country or "").strip().lower(), salary_min or 0)
        cached = Job._cache_get_count(key)
        if cached is not None:
            return cached
        where_sql, params_pg = Job._where(title, country, salary_min=salary_min)
        db = get_db()
        with db.cursor() as cur:
            cur.execute(f"SELECT COUNT(1) FROM jobs {where_sql}", params_pg)
            row = cur.fetchone()
            value = int(row[0] if row else 0)
            Job._cache_set_count(key, value)
            return value

    @staticmethod
    def search(
        title: Optional[str] = None,
        country: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        salary_min: Optional[int] = None,
    ) -> List[Dict]:
        """Return matching jobs ordered by recency."""
        key = (
            (title or "").strip().lower(),
            (country or "").strip().lower(),
            int(limit),
            int(offset),
            salary_min or 0,
        )
        cached = Job._cache_get_search(key)
        if cached is not None:
            return cached
        where_sql, params_pg = Job._where(title, country, salary_min=salary_min)
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
        except Exception:
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
    def _where(title: Optional[str], country: Optional[str], salary_min: Optional[int] = None) -> Tuple[str, Tuple]:
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

        where_pg = f"WHERE {' AND '.join(clauses_pg)}" if clauses_pg else ""
        return where_pg, tuple(params_pg)

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
