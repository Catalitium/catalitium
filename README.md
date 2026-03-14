# Catalitium

> Solutions

---

## Soul

We move fast, stay lean, and let software do the heavy lifting.
Swiss precision, no fluff. Automation over complexity. Work smart, not hard.
Direct. Honest. Efficient. No corporate speak.

## Mission

Companies waste money on solutions that are too complicated.
Talent doesn't know what they're worth. Job markets are a black box.
We build simple tools that connect people with what they need to grow — faster, cheaper, smarter.
We remove the noise so people can focus on what matters.

## Vision

Every company gets the tools they need, regardless of budget.
Every professional knows their market value.
Software handles the hard work so humans do the meaningful work.

---

## What we built

**Catalitium** is a career intelligence platform for tech talent — curated jobs, salary insights, and market research in one place.

- **Smart job search** — title synonyms, fuzzy matching, location normalization
- **Salary Tool** — interactive benchmarks + talent arbitrage calculator
- **Market Research** — curated reports on AI, hiring trends, and salary data
- **Weekly Digest** — curated role alerts with salary signal, one email per week
- **Salary Board** — recruiter-grade salary browser with filters

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | Flask 2.2+ · Python 3.11+ |
| Database | Supabase |
| Frontend | Jinja2 + Tailwind CSS (local build) |
| Server | Gunicorn |

---

## Local setup

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # set SUPABASE_URL and SECRET_KEY
python run.py
```

## Tailwind CSS build

After template changes that introduce new CSS classes, rebuild the stylesheet:

```bash
node_modules/.bin/tailwindcss -i app/static/css/tailwind.input.css -o app/static/css/tailwind.css --minify
```

Or install deps first if `node_modules/` is missing:

```bash
npm install
node_modules/.bin/tailwindcss -i app/static/css/tailwind.input.css -o app/static/css/tailwind.css --minify
```

> **Note:** `tailwindcss` and `@tailwindcss/cli` are declared as `devDependencies` in `package.json`. Use `npm install` (not `npm install --production`) to get them.

---

MIT © 2026 Catalitium
