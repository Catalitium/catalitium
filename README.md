# Catalitium

> AI-powered job platform and automation tools for tech talent and companies.

---

## Soul

Move fast. Stay lean. Let software do the heavy lifting.
Automation over complexity. Outcomes over effort. Intelligence over headcount.
Direct. Honest. Efficient.

## Mission

Companies waste money on overcomplicated solutions.
Talent doesn't know what they're worth. Job markets are a black box.
We build lean tools that connect people with what they need to grow — faster, cheaper, smarter.
We remove the noise so people can focus on what matters.

## Vision

Every company gets the tools they need, regardless of size or budget.
Every professional knows their market value and how to improve it.
AI and software handle the heavy lifting so humans do the meaningful work.

---

## What We Built

**Catalitium** is a career intelligence platform for tech talent — curated jobs, salary insights, market research, and developer API access in one place.

| Feature | Description |
|---------|-------------|
| **Smart Job Search** | Title synonyms, fuzzy matching, location normalization, 50K+ curated roles |
| **Salary Tool** | Interactive benchmarks, talent arbitrage calculator, delta badges |
| **Market Research** | Curated reports on AI adoption, hiring trends, and salary dynamics |
| **Weekly Digest** | High-signal role alerts with salary data, one email per week |
| **Salary Board** | Recruiter-grade salary browser with region and role filters |
| **Developer API** | Account-gated REST API (`/v1/jobs`, `/v1/salary`) — 50 req/day free |
| **Recruiter Dashboard** | Post jobs, track listings, 10-day active window per post |
| **Freemium Gate** | Guests see up to 5,000 jobs/day; signed-in users get full access |

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | Flask 3.1 · Python 3.11+ |
| Database | Supabase (PostgreSQL) |
| Auth | Supabase Auth (email + password) |
| Frontend | Jinja2 + Tailwind CSS (CDN) |
| Payments | Stripe (pay-per-post) |
| Server | Gunicorn · gthread · systemd |
| Deployment | Hetzner VPS · Nginx reverse proxy |

---

## Local Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # fill in DATABASE_URL, SECRET_KEY, Supabase keys
python run.py
```

Visit `http://localhost:5000`

---

## Project Structure

```
catalitium/
├── app/
│   ├── app.py                  # Flask app factory — all routes, rate limiting, auth
│   ├── api_utils.py            # JSON envelopes, query param helpers, TTL cache
│   ├── models/
│   │   └── db.py               # DB queries, connection pool, API key management
│   ├── static/
│   │   ├── css/styles.css      # Custom styles
│   │   ├── js/                 # main.js, sw.js, ai_summary.js, tracker.js
│   │   └── img/                # Logos, favicons
│   └── views/
│       └── templates/          # Jinja2 HTML templates
│           ├── base.html       # Layout, nav, service worker, cookie consent
│           ├── components/     # Reusable partials (job_card, promo_card)
│           └── reports/        # Market research report pages
├── scripts/                    # Utility scripts (email digest, smoke tests)
├── tests/                      # Pytest smoke + prod-readiness tests
├── public/                     # Static assets served directly (testimonial images)
├── .env.example                # All required env vars — copy to .env to run locally
├── requirements.txt            # Pinned Python dependencies
└── run.py                      # Local dev entry point (Gunicorn in prod)
```

---

## API Access

Signed-in users can register a free API key at `POST /api/keys/register`.
Once activated via email, use the key as a header on all `/v1/` endpoints:

```bash
curl https://catalitium.com/v1/jobs?title=python \
  -H "X-API-Key: cat_your_key_here"
```

**Endpoints**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/jobs` | Search jobs (params: `title`, `country`, `page`) |
| `GET` | `/v1/jobs/<id>` | Single job detail |
| `GET` | `/v1/salary` | Salary lookup by title + country |
| `GET` | `/api/keys/usage` | Daily quota and reset time |

Free tier: **50 requests/day** · Reset: UTC midnight

---

## Future Enhancements

### User Growth

| Tactic | How Catalitium Executes | Target Impact |
|--------|------------------------|---------------|
| **Viral Referral Bot** | "Share 3 jobs → free month of alerts" | 15% MoM growth |
| **Salary Alert Agent** | Daily: "New €120k Python roles in Zurich" | 3× activation |
| **LinkedIn Lead Gen** | Prospect hook: "Your market salary: €95k" | 500 leads/mo |
| **Ghost Job Flagger** | Real-time dead listing detection and alerts | Viral trust signal |
| **A/B Landing Tester** | Auto-optimises headlines and CTAs | +22% conversions |

### Retention

| Tactic | How Catalitium Executes | Target Impact |
|--------|------------------------|---------------|
| **Personal Job Agent** | "Juan: 7 new matches this week" weekly digest | 40% lower churn |
| **Churn Predictor** | Flags at-risk users → "Unlock premium alerts?" | +18% LTV |
| **Usage Gamifier** | "Beat your job search streak → bonus credits" | 28% daily active |
| **Support Automator** | "Job expired? Here are 5 replacements" | 90% self-serve |
| **Winback Hunter** | Ex-users: "1M+ new jobs since you left" | 12% reactivation |

---

## Pull requests

1. Open a PR against the target branch (e.g. `main`) from your feature branch.
2. **Smoke-test locally**: `python run.py`, hit the pages or flows you changed.
3. Do **not** commit secrets (`.env`), `__pycache__/`, or local scratch files — see `.gitignore`.
4. Describe **what** changed and **why** in the PR body (the template prompts you on GitHub).

---

MIT © 2026 Catalitium
