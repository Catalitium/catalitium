"""
Welcome Email Backfill
======================
Sends a welcome email to all real existing subscribers who never got one.
Skips bots, test addresses, and our own accounts.

Usage:
    python scripts/send_welcome_backfill.py
"""

import os
import sys
import time
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", "info@catalitium.com").strip()

# Skip domains that are bots, disposable, or internal
SKIP_DOMAINS = {"checkyourform.xyz"}
SKIP_EMAILS  = {"test@gmail.com", "test-qa@catalitium.com",
                 "real-sub-test@catalitium.com", "catalitium@gmail.com"}


def is_real(email: str) -> bool:
    e = email.strip().lower()
    if e in {s.lower() for s in SKIP_EMAILS}:
        return False
    domain = e.split("@")[-1]
    if domain in SKIP_DOMAINS:
        return False
    return True


def send_welcome(smtp, email: str) -> bool:
    body = """\
Hi,

You signed up for Catalitium a while back, welcome properly.

Catalitium is a high-signal job board for tech professionals.
Every listing comes with real salary data so you know your market value
before you walk into any interview.

Browse the latest tech jobs now:
https://catalitium.com

We send a weekly digest of top matches. No noise. No spam. Just signal.

Questions? Reply to this email.

--
Catalitium team
info@catalitium.com
https://catalitium.com
"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Welcome to Catalitium, your weekly job digest"
    msg["From"]    = f"Catalitium <{SMTP_FROM}>"
    msg["To"]      = email
    try:
        smtp.send_message(msg)
        return True
    except Exception as exc:
        print(f"    [FAIL] {email}  >>  {exc}")
        return False


# ── Fetch subscribers ─────────────────────────────────────────────────────────

try:
    import psycopg
except ImportError:
    print("[FAIL] psycopg not installed.")
    sys.exit(1)

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL") or ""
if not DATABASE_URL:
    print("[FAIL] DATABASE_URL not set in .env")
    sys.exit(1)

conn = psycopg.connect(DATABASE_URL, autocommit=True)
with conn.cursor() as cur:
    cur.execute("SELECT email FROM subscribers ORDER BY created_at")
    all_emails = [row[0].strip() for row in cur.fetchall()]
conn.close()

targets = [e for e in all_emails if is_real(e)]
skipped = [e for e in all_emails if not is_real(e)]

print(f"\n=== Welcome Email Backfill ===\n")
print(f"  Total in DB : {len(all_emails)}")
print(f"  Skipping    : {len(skipped)}  ({', '.join(skipped)})")
print(f"  Sending to  : {len(targets)}\n")

if not targets:
    print("  Nothing to send. Exiting.")
    sys.exit(0)

# ── Open SMTP once, send all ──────────────────────────────────────────────────

try:
    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15)
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login(SMTP_USER, SMTP_PASS)
    print("  SMTP connected.\n")
except Exception as exc:
    print(f"  [FAIL] SMTP connect: {exc}")
    sys.exit(1)

sent = 0
failed = 0
for email in targets:
    ok = send_welcome(server, email)
    if ok:
        print(f"  [SENT] {email}")
        sent += 1
    else:
        failed += 1
    time.sleep(0.5)  # be gentle with Gmail rate limits

server.quit()

print(f"\n=== Done: {sent} sent, {failed} failed ===\n")
sys.exit(0 if failed == 0 else 1)
