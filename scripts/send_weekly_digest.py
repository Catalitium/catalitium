"""
Weekly Digest Sender
====================
Fetches top jobs from Supabase, personalizes per subscriber search context,
and sends one email per subscriber.

Usage:
    python scripts/send_weekly_digest.py

Schedule with cron (Linux/Mac):
    0 8 * * 1  /path/to/venv/bin/python /path/to/scripts/send_weekly_digest.py

Schedule with Task Scheduler (Windows):
    Action: python scripts/send_weekly_digest.py
    Trigger: Weekly, Monday 08:00
"""

import os
import sys
import time
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

try:
    import psycopg
except ImportError:
    print("[FAIL] psycopg not installed.")
    sys.exit(1)

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or ""
SMTP_HOST    = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT    = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER    = os.getenv("SMTP_USER", "").strip()
SMTP_PASS    = os.getenv("SMTP_PASS", "").strip()
SMTP_FROM    = os.getenv("SMTP_FROM", "info@catalitium.com").strip()
BASE_URL     = os.getenv("BASE_URL", "https://catalitium.com").rstrip("/")

JOBS_PER_DIGEST = 5

# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_salary(job: dict) -> str:
    sal = (job.get("job_salary_range") or "").strip()
    if sal:
        return sal
    low  = job.get("salary_low")
    high = job.get("salary_high")
    if low and high:
        return f"${int(low):,} - ${int(high):,}"
    if low:
        return f"${int(low):,}+"
    return "Salary not listed"


def job_block(job: dict) -> str:
    title    = job.get("title") or job.get("job_title") or "Role"
    company  = job.get("company") or "Company"
    location = job.get("location") or "Remote"
    salary   = fmt_salary(job)
    link     = job.get("link") or BASE_URL
    url      = link or BASE_URL
    return (
        f"  {title} at {company}\n"
        f"  {location} | {salary}\n"
        f"  {url}\n"
    )


def build_email(subscriber: dict, jobs: list) -> str:
    email         = subscriber["email"]
    search_title  = (subscriber.get("search_title") or "").strip()
    search_country= (subscriber.get("search_country") or "").strip()
    salary_band   = (subscriber.get("search_salary_band") or "").strip()

    if search_title and search_country:
        context_line = f"Top {search_title} jobs in {search_country} this week"
    elif search_title:
        context_line = f"Top {search_title} jobs this week"
    elif search_country:
        context_line = f"Top tech jobs in {search_country} this week"
    else:
        context_line = "Top tech jobs this week"
    if salary_band:
        context_line += f" ({salary_band})"

    week = datetime.now(timezone.utc).strftime("%B %d, %Y")
    jobs_text = "\n".join(job_block(j) for j in jobs)

    return f"""\
Catalitium Weekly Digest - {week}
{context_line}
{'=' * 50}

{jobs_text}
Browse all jobs: {BASE_URL}

{'=' * 50}
You're receiving this because you subscribed at catalitium.com.
Reply 'unsubscribe' to be removed.
"""


def fetch_subscribers(conn) -> list:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT email, search_title, search_country, search_salary_band
            FROM subscribers
            ORDER BY created_at
        """)
        cols = ["email", "search_title", "search_country", "search_salary_band"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_jobs(conn, title: str = "", country: str = "", limit: int = JOBS_PER_DIGEST) -> list:
    clauses = []
    params  = []

    if title:
        clauses.append("LOWER(job_title) LIKE %s")
        params.append(f"%{title.lower()}%")
    if country:
        clauses.append("LOWER(location) LIKE %s")
        params.append(f"%{country.lower()}%")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql   = f"""
        SELECT job_title AS title, company_name AS company, location, salary AS job_salary_range, link, job_id AS slug
        FROM jobs
        {where}
        ORDER BY date DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = ["title", "company", "location", "job_salary_range", "link", "slug"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def send_email(smtp, to: str, subject: str, body: str) -> bool:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = f"Catalitium <{SMTP_FROM}>"
    msg["To"]      = to
    try:
        smtp.send_message(msg)
        return True
    except Exception as exc:
        print(f"    [FAIL] {to} >> {exc}")
        return False


# ── Skip list (bots / internal) ───────────────────────────────────────────────

SKIP_DOMAINS = {"checkyourform.xyz"}
SKIP_EMAILS  = {"test@gmail.com", "test-qa@catalitium.com",
                 "real-sub-test@catalitium.com"}

def is_real(email: str) -> bool:
    e = email.strip().lower()
    if e in {s.lower() for s in SKIP_EMAILS}:
        return False
    return e.split("@")[-1] not in SKIP_DOMAINS


# ── Main ──────────────────────────────────────────────────────────────────────

print(f"\n=== Catalitium Weekly Digest - {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

if not all([DATABASE_URL, SMTP_HOST, SMTP_USER, SMTP_PASS]):
    print("[FAIL] Missing DATABASE_URL or SMTP config in .env")
    sys.exit(1)

conn = psycopg.connect(DATABASE_URL, autocommit=True)

all_subs = fetch_subscribers(conn)
targets  = [s for s in all_subs if is_real(s["email"])]
print(f"  Subscribers: {len(all_subs)} total, {len(targets)} real\n")

try:
    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15)
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login(SMTP_USER, SMTP_PASS)
    print("  SMTP connected.\n")
except Exception as exc:
    print(f"  [FAIL] SMTP: {exc}")
    conn.close()
    sys.exit(1)

sent = failed = 0

for sub in targets:
    jobs = fetch_jobs(conn, title=sub.get("search_title") or "", country=sub.get("search_country") or "")
    if not jobs:
        # fallback: send top jobs regardless of filter
        jobs = fetch_jobs(conn)
    if not jobs:
        print(f"  [SKIP] {sub['email']} >> no jobs found")
        continue

    subject = "Catalitium: your weekly tech job digest"
    body    = build_email(sub, jobs)
    ok      = send_email(server, sub["email"], subject, body)

    if ok:
        ctx = f"{sub.get('search_title') or ''} {sub.get('search_country') or ''}".strip() or "general"
        print(f"  [SENT] {sub['email']}  ({ctx}, {len(jobs)} jobs)")
        sent += 1
    else:
        failed += 1

    time.sleep(0.5)

server.quit()
conn.close()

print(f"\n=== Done: {sent} sent, {failed} failed ===\n")
sys.exit(0 if failed == 0 else 1)
