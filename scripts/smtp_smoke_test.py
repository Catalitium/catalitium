"""
SMTP Smoke Test
===============
Sends a real test email via Gmail SMTP before touching the main app.
Reads config from .env.

Usage:
    python scripts/smtp_smoke_test.py
"""

import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
SMTP_FROM = os.getenv("SMTP_FROM", "").strip()

results = []

def check(label, ok, detail=""):
    icon = "[PASS]" if ok else "[FAIL]"
    print(f"  {icon} {label}" + (f"  >>  {detail}" if detail else ""))
    results.append(ok)

print("\n=== SMTP Smoke Test ===\n")

# Check 1: config present
check(".env SMTP_HOST set", bool(SMTP_HOST), SMTP_HOST or "MISSING")
check(".env SMTP_USER set", bool(SMTP_USER), SMTP_USER or "MISSING")
check(".env SMTP_PASS set", bool(SMTP_PASS), "***" if SMTP_PASS else "MISSING")
check(".env SMTP_FROM set", bool(SMTP_FROM), SMTP_FROM or "MISSING")

if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, SMTP_FROM]):
    print("\n[FAIL] Missing SMTP config. Check .env.\n")
    sys.exit(1)

# Check 2: TCP connect
try:
    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
    check("TCP connect to SMTP host", True, f"{SMTP_HOST}:{SMTP_PORT}")
except Exception as exc:
    check("TCP connect to SMTP host", False, str(exc))
    sys.exit(1)

# Check 3: STARTTLS
try:
    server.ehlo()
    server.starttls()
    server.ehlo()
    check("STARTTLS handshake", True)
except Exception as exc:
    check("STARTTLS handshake", False, str(exc))
    server.quit()
    sys.exit(1)

# Check 4: Login
try:
    server.login(SMTP_USER, SMTP_PASS)
    check("SMTP login", True, SMTP_USER)
except Exception as exc:
    check("SMTP login", False, str(exc))
    server.quit()
    sys.exit(1)

# Check 5: Send real test email
TO = SMTP_USER  # send to self as smoke test
try:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "[Catalitium] SMTP Smoke Test"
    msg["From"] = f"Catalitium <{SMTP_FROM}>"
    msg["To"] = TO

    text = "SMTP smoke test passed. Catalitium email is working."
    html = """\
<html><body>
<p style="font-family:sans-serif;font-size:15px;">
  <strong>SMTP smoke test passed.</strong><br>
  Catalitium can send emails from <code>{frm}</code> via Gmail SMTP.<br><br>
  <span style="color:#6b7280;font-size:13px;">You can delete this email.</span>
</p>
</body></html>""".format(frm=SMTP_FROM)

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    server.sendmail(SMTP_FROM, TO, msg.as_string())
    server.quit()
    check("Test email sent", True, f"delivered to {TO}")
except Exception as exc:
    check("Test email sent", False, str(exc))
    sys.exit(1)

total = len(results)
passed = sum(results)
print(f"\n=== Result: {passed}/{total} checks passed", end="")
print("  -- ALL GOOD" if passed == total else f"  ({total-passed} failed)")
print(f"\n  Check inbox: {TO}\n")
sys.exit(0 if passed == total else 1)
