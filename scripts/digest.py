#!/usr/bin/env python3
"""Weekly digest runner — fetch top jobs and email one digest per subscriber.

Usage (from repo root):
    python scripts/digest.py

Requires .env with DATABASE_URL and SMTP_* configured.
Exit 0 on success, 1 on any failure.
"""

from __future__ import annotations

import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

DIGEST_JOBS_PER_SEND: int = 5
_DIGEST_SKIP_DOMAINS: frozenset = frozenset({"checkyourform.xyz"})
_DIGEST_SKIP_EMAILS: frozenset = frozenset({
    "test@gmail.com", "test-qa@catalitium.com", "real-sub-test@catalitium.com",
})


def _digest_fmt_salary(job: dict) -> str:
    sal = (job.get("job_salary_range") or "").strip()
    if sal:
        return sal
    low = job.get("salary_low")
    high = job.get("salary_high")
    if low and high:
        return f"${int(low):,} - ${int(high):,}"
    if low:
        return f"${int(low):,}+"
    return "Salary not listed"


def _digest_job_block(job: dict) -> str:
    base = os.getenv("BASE_URL", "https://catalitium.com").rstrip("/")
    return (
        f"  {job.get('title') or job.get('job_title') or 'Role'}"
        f" at {job.get('company') or 'Company'}\n"
        f"  {job.get('location') or 'Remote'} | {_digest_fmt_salary(job)}\n"
        f"  {job.get('link') or base}\n"
    )


def build_digest_email(subscriber: dict, jobs: list) -> str:
    """Compose the weekly digest email body for one subscriber."""
    base = os.getenv("BASE_URL", "https://catalitium.com").rstrip("/")
    search_title = (subscriber.get("search_title") or "").strip()
    search_country = (subscriber.get("search_country") or "").strip()
    salary_band = (subscriber.get("search_salary_band") or "").strip()
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
    jobs_text = "\n".join(_digest_job_block(j) for j in jobs)
    return (
        f"Catalitium Weekly Digest - {week}\n"
        f"{context_line}\n"
        f"{'=' * 50}\n\n"
        f"{jobs_text}\n"
        f"Browse all jobs: {base}\n\n"
        f"{'=' * 50}\n"
        f"You're receiving this because you subscribed at catalitium.com.\n"
        f"Unsubscribe: {base}/unsubscribe\n"
    )


def is_real_subscriber(email: str) -> bool:
    """Return False for known test/bot addresses."""
    e = email.strip().lower()
    if e in {s.lower() for s in _DIGEST_SKIP_EMAILS}:
        return False
    return e.split("@")[-1] not in _DIGEST_SKIP_DOMAINS


def run_weekly_digest() -> int:
    """Fetch top jobs and send one digest email per subscriber. Returns exit code."""
    try:
        import psycopg  # noqa: PLC0415
    except ImportError:
        print("[FAIL] psycopg not installed.")
        return 1

    database_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or ""
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").strip()
    smtp_from = os.getenv("SMTP_FROM", "info@catalitium.com").strip()

    print(f"\n=== Catalitium Weekly Digest - {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    if not all([database_url, smtp_host, smtp_user, smtp_pass]):
        print("[FAIL] Missing DATABASE_URL or SMTP config in .env")
        return 1

    conn = psycopg.connect(database_url, autocommit=True)

    def _fetch_subscribers(c) -> list:
        with c.cursor() as cur:
            cur.execute(
                "SELECT email, search_title, search_country, search_salary_band "
                "FROM subscribers ORDER BY created_at"
            )
            cols = ["email", "search_title", "search_country", "search_salary_band"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _fetch_jobs(c, title: str = "", country: str = "", limit: int = DIGEST_JOBS_PER_SEND) -> list:
        clauses, params = [], []
        if title:
            clauses.append("LOWER(job_title) LIKE %s")
            params.append(f"%{title.lower()}%")
        if country:
            clauses.append("LOWER(location) LIKE %s")
            params.append(f"%{country.lower()}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT job_title AS title, company_name AS company, location, "
            f"salary AS job_salary_range, link, job_id AS slug FROM jobs "
            f"{where} ORDER BY date DESC NULLS LAST LIMIT %s"
        )
        params.append(limit)
        with c.cursor() as cur:
            cur.execute(sql, params)
            cols = ["title", "company", "location", "job_salary_range", "link", "slug"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    all_subs = _fetch_subscribers(conn)
    targets = [s for s in all_subs if is_real_subscriber(s["email"])]
    print(f"  Subscribers: {len(all_subs)} total, {len(targets)} real\n")

    try:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        print("  SMTP connected.\n")
    except Exception as exc:
        print(f"  [FAIL] SMTP: {exc}")
        conn.close()
        return 1

    sent = failed = 0
    for sub in targets:
        jobs = _fetch_jobs(conn, title=sub.get("search_title") or "", country=sub.get("search_country") or "")
        if not jobs:
            jobs = _fetch_jobs(conn)
        if not jobs:
            print(f"  [SKIP] {sub['email']} >> no jobs found")
            continue
        body = build_digest_email(sub, jobs)
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = "Catalitium: your weekly tech job digest"
        msg["From"] = f"Catalitium <{smtp_from}>"
        msg["To"] = sub["email"]
        try:
            server.send_message(msg)
            ctx = f"{sub.get('search_title') or ''} {sub.get('search_country') or ''}".strip() or "general"
            print(f"  [SENT] {sub['email']}  ({ctx}, {len(jobs)} jobs)")
            sent += 1
        except Exception as exc:
            print(f"    [FAIL] {sub['email']} >> {exc}")
            failed += 1
        time.sleep(0.5)

    server.quit()
    conn.close()
    print(f"\n=== Done: {sent} sent, {failed} failed ===\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_weekly_digest())
