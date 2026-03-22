# Catalitium – Chat History & Context

## Opening Prompt for New Chat

> We are building Stripe payments into catalitium.com. B2B (job postings) and B2C (Market Intelligence + API Access subscriptions) are both implemented and deployed to main. The webhook is registered at `https://catalitium.com/stripe/webhook`. We need to [describe next task — e.g. test end-to-end / gate content / add Elite Plan multi-slot].

---

## Session: Stripe B2B Integration (March 2026)

### Goal
Allow companies to pay via Stripe to post jobs. Three products:

| Plan | Type | Price | Env var |
|------|------|-------|---------|
| Core Post | One-time | $109 | `STRIPE_PRICE_CORE_POST` |
| Premium Post | One-time | $219 | `STRIPE_PRICE_PREMIUM_POST` |
| Elite Plan | Subscription | $379/mo | `STRIPE_PRICE_ELITE_PLAN` |

### Flow
1. Company logs in → `/post-a-job`
2. Selects plan → POSTs to `/stripe/checkout`
3. Stripe Checkout Session created → redirect to Stripe
4. After payment → `/stripe/success?session_id=xxx`
5. Company fills job details → `/stripe/submit-job`
6. Admin + company receive email; webhook marks order `paid`

### Files (committed to main, commit `04921d1`)
- `app/app.py` — 6 routes: `/post-a-job`, `/stripe/checkout`, `/stripe/success`, `/stripe/submit-job`, `/stripe/cancel`, `/stripe/webhook`
- `app/models/db.py` — `stripe_orders` table + 4 helpers: `insert_stripe_order`, `mark_stripe_order_paid`, `mark_stripe_order_job_submitted`, `get_stripe_order`
- `requirements.txt` — `stripe==11.4.1`
- Templates: `post_job_pricing.html`, `post_job_submit.html`, `stripe_cancel.html`

---

## Session: Stripe B2C Subscriptions (March 2026)

### Goal
Allow individuals/companies to subscribe to Market Intelligence and API Access tiers.

### Products

| Plan | Product Line | Tier | Price | Env var |
|------|-------------|------|-------|---------|
| MI Free | market_intelligence | free | $0 | — |
| MI Premium | market_intelligence | premium | $9/mo | `STRIPE_PRICE_MI_PREMIUM` |
| MI Pro | market_intelligence | pro | $99/mo | `STRIPE_PRICE_MI_PRO` |
| API Free | api_access | free | $0 | — |
| API Access | api_access | api | $4.99/mo | `STRIPE_PRICE_API_ACCESS` |

### Flow
1. User visits `/pricing` → sees both product lines with their current plan highlighted
2. Clicks Subscribe → POSTs to `/stripe/subscribe`
   - If no existing sub for that product line: new Stripe Checkout Session
   - If already subscribed: in-place upgrade/downgrade via `Subscription.modify()` (proration applied)
3. After payment → `/stripe/subscription/success?plan_key=xxx`
4. Manage / cancel at `/account/subscription`
5. Webhook keeps DB in sync on all subscription lifecycle events

### Webhook events handled (all in `POST /stripe/webhook`)
| Event | Action |
|-------|--------|
| `checkout.session.completed` | Marks B2B order paid |
| `customer.subscription.created` | Upserts subscription row |
| `customer.subscription.updated` | Upserts subscription row (handles plan changes) |
| `customer.subscription.deleted` | Marks subscription `cancelled` |
| `invoice.payment_succeeded` | Re-syncs subscription (updates period end) |
| `invoice.payment_failed` | Marks subscription `past_due` |

---

## Session: Paywall, Pricing Tiers & Deployment (March 2026)

### What was done
- Market Intelligence gating: 3 reports gated behind Premium/Pro (200K Engineer, SaaS to Agents, Death of SaaS). Free users see header + KPI teaser + paywall CTA (`_paywall.html`)
- PDF/print button hidden for free users on gated reports
- Market research index shows lock badge + "Preview" CTA for free users
- `_get_mi_tier()` helper resolves user's active MI tier from DB
- Pricing link added to desktop nav + replaces Subscribe in mobile nav
- API key free quota corrected 100 → 500 calls/month
- `update_api_key_limit_by_email()` syncs quota on subscription events (active → 10,000; else → 500)
- Hardcoded Stripe price ID fallbacks removed — env vars are sole source of truth
- B2B `/stripe/checkout` now guards empty `price_id` (matches B2C)
- Merge conflicts resolved: kept 500 monthly_limit + daily quota columns from remote API branch

### Commits on main (as of this session)
```
553d149  chore: resolve merge conflicts — keep 500 monthly_limit + daily quota columns + B2C env keys
065097c  Merge stripe-b2c: B2C subscriptions, paywall, pricing tiers, key hygiene
eb34a39  fix: remove hardcoded Stripe price ID fallbacks + guard B2B checkout
99346de  feat: wire pricing tiers to functional limitations
cb79963  feat: Stripe B2C subscriptions — Market Intelligence & API Access
04921d1  feat: Stripe B2B job posting payments
```

---

## `.env` (local only, never committed)
All real keys:
- `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`
- B2B: `STRIPE_PRICE_CORE_POST`, `STRIPE_PRICE_PREMIUM_POST`, `STRIPE_PRICE_ELITE_PLAN`
- B2C: `STRIPE_PRICE_MI_PREMIUM`, `STRIPE_PRICE_MI_PRO`, `STRIPE_PRICE_API_ACCESS`
- `ADMIN_EMAIL=stoicosemper@proton.me`
- `ASSET_VERSION`, `DATABASE_URL`, `SECRET_KEY`, `SUPABASE_*`, `SMTP_*`, `ANTHROPIC_API_KEY`

---

## Stripe Dashboard Setup
- Webhook: `https://catalitium.com/stripe/webhook`
- Signing secret in `.env` as `STRIPE_WEBHOOK_SECRET`
- **Required webhook events:** `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_succeeded`, `invoice.payment_failed`

---

## What still needs doing

### Deploy (immediate)
- [ ] Pull & restart Gunicorn on production server (`git pull origin main && sudo systemctl restart gunicorn`)
- [ ] Add 3 B2C price env vars to production `.env` if not already there
- [ ] Confirm Stripe Dashboard has all 6 webhook events enabled

### Testing
- [ ] Test B2C subscription flow end-to-end with test card `4242 4242 4242 4242`
- [ ] Test upgrade (MI Premium → Pro) and cancel flows
- [ ] Test B2B job posting end-to-end
- [ ] Verify paywall shows for free users on gated reports; unlocks after subscribing

### Product
- [ ] Handle Elite Plan multi-slot job submissions (3 posts/month; currently 1 form per order)
- [ ] Add `/hire` dashboard panel showing active B2B orders and status
- [ ] Switch all price IDs and keys from test to live before going to production

---

## Key architectural notes
- Stack: Flask 3.1, Supabase (PostgreSQL via psycopg v3), Tailwind CSS CDN, Gunicorn
- Auth: Supabase auth in Flask `session["user"]` — keys: `id`, `email`, `account_type`, `hire_access`
- CSRF: `session["_csrf_token"]` validated via `_csrf_valid()` — webhook bypasses this
- Email: `_send_mail(to, subject, body)` via SMTP (`SMTP_*` env vars)
- DB helpers return `"ok"` or `"error"` string
- All templates extend `base.html`, use `{{ csrf_token() }}` in forms
- `user_subscriptions` status values: `active`, `past_due`, `cancelled`
- Upgrade/downgrade: in-place `Subscription.modify()` with `proration_behavior="create_prorations"`; webhook syncs DB
- `api_keys` table has both monthly (`monthly_limit`, `requests_this_month`, `month_window`) and daily (`daily_limit`, `requests_today`, `day_window`) quota columns
- Free API tier: 500 calls/month, 50/day. Paid API tier: 10,000/month
- Gated reports: `"gated": True` in `REPORTS` list; `_get_mi_tier()` checks DB for active MI sub
- 404 handler returns JSON for all requests

---

## Session: Landing Page Redesign (March 2026)

### Goal
Create a premium, modern, tech-forward marketing landing page at `/` to showcase Catalitium's four business areas (Job Platform, Market Intelligence, Software Development, AI Agents as a Service), and move the existing job search functionality to `/jobs`.

### Architecture & Route Restructure
- Renamed `def index()` to `def jobs()` and moved its route from `/` to `/jobs`.
- Added new `def landing()` route at `/` to render the new `landing.html` template, loading up to 4 featured jobs from the DB.
- Added 301 redirect logic for legacy `/?title=...` URLs to forward to `/jobs?title=...`.
- Updated over 100 `url_for("index")` references across 19 files (templates and Python) to `url_for("jobs")`.
- Updated navigation links in `base.html`: Logo links to `/`, "Jobs" links to `/jobs`.

### Visual Design & Landing Page Sections
- **Hero**: "Automation over complexity." with animated gradient orbs (added to `styles.css`) and CTAs.
- **Stats Bar**: Live active jobs count, 40+ countries, 10K+ salary data points.
- **Services Grid**: 4 premium cards with color-coded icons and hover glow effects.
- **Live Jobs Preview**: 4 featured job cards fetched directly from the database.
- **Market Intelligence Teaser**: Side-by-side text and blue gradient visual.
- **AI Agents**: 3-step autonomous process overview with emerald/cyan/violet accents.
- **Pricing Teaser**: 3 compact subscription tier cards.
- **Final CTA**: "Move fast. Stay lean." gradient section.

### Files Modified & Created
- **Created**: `app/views/templates/landing.html`
- **Modified**: `app/app.py` (route changes), `app/views/templates/base.html` (wide layout toggle, nav links), `app/static/css/styles.css` (gradient animations).
- **Updated `url_for` references**: `index.html`, `job_browser.html`, `job_detail.html`, `studio.html`, `salary_report.html`, `resources.html`, `subscription_success.html`, `job_card.html`, `market_research_index.html`, `tracker.html`, `stripe_cancel.html`, and 5 report templates.

---

## Session: Landing Page Light/Dark Mode Fix (March 2026)

### Problem
Sections 1 (Hero), 6 (AI Agents as a Service), and 8 (Final CTA) used hardcoded `bg-slate-950` with white text — always appearing dark regardless of system or user preference. Dark mode is class-based (`darkMode: 'class'` in Tailwind config), so without the `dark` class on `<html>`, those sections had no light fallback.

### Fix
All three sections now fully support both modes using `dark:` Tailwind variants:

| Section | Before | After |
|---------|--------|-------|
| Hero (1) | `bg-slate-950` (hardcoded dark) | `bg-white dark:bg-slate-950` |
| AI Agents (6) | `bg-slate-950 text-white` (hardcoded dark) | `bg-slate-50 dark:bg-slate-950` |
| Final CTA (8) | `bg-slate-950` (hardcoded dark) | `bg-white dark:bg-slate-950` |

Additional changes per section:
- **Hero**: Status pill, h1, subtext, CTA buttons all get `dark:` variants. Dot grid split into two divs (black dots in light, white dots in dark). "Explore jobs" CTA uses brand blue in light / white in dark.
- **AI Agents**: All headings, step titles, descriptions, icon colours, and the gradient "Autonomously." text adapted.
- **Final CTA**: Gradient overlay adapted, both CTA buttons adapted, divider uses `border-slate-200 dark:border-slate-800`.

### Commits
```
ecb4957  fix(ui): make landing page fully responsive to light/dark mode
068476a  (merged to main, rebased on df19d47)
```

---

## Session: UI Polish & SEO (March 2026)

### Changes Made

**Favicon**
- Removed conflicting SVG data-URI favicon (blue circle with "C") from `base.html` line ~69 that was overriding the `logo.png` favicon links already defined above it.
- `logo.png` now correctly serves as favicon across all browsers and devices (32×32, 16×16, 192×192, apple-touch-icon).

**Header: Centered Navigation**
- Restructured the desktop header from a single flexbox row to a 3-column CSS grid (`xl:grid-cols-[1fr_auto_1fr]`).
- Left col (1fr): hamburger + logo. Center col (auto + `justify-center`): nav links. Right col (1fr + `justify-end`): action buttons.
- Achieves true centering of nav links regardless of logo/button widths. Mobile layout unchanged.
- File: `app/views/templates/base.html`

**SEO Fixes** (based on Gemini scan of live site)
- **Meta description** trimmed from 179 → 145 chars in `landing.html` (was truncated by Google).
- **H1 structure**: "over complexity." text node moved inside the gradient `<span>` so scanners read one unified heading instead of two split text fragments.
- File: `app/views/templates/landing.html`

**Landing Page CTA Wiring**
- "Start a conversation" button (AI Agents section) changed from `url_for('about')` → `url_for('register')`.
- "Subscribe to Weekly Digest" bell link changed from `<a href=url_for('jobs')>` → `<button data-open-subscribe>` to trigger the existing subscription modal.
- File: `app/views/templates/landing.html`

**Social Media Icons — Footer**
- Added a row of 7 icon buttons to the footer brand column (below SOC 2 / GDPR badges).
- Platforms: LinkedIn, X/Twitter, Instagram, YouTube, TikTok, Discord, Telegram.
- Styled as `w-8 h-8` bordered icon buttons with `hover:text-brand hover:border-brand` transition.
- All open `target="_blank" rel="noopener noreferrer"` with `aria-label` for accessibility.
- File: `app/views/templates/base.html`

### Social Media URLs
| Platform | URL |
|----------|-----|
| LinkedIn | https://www.linkedin.com/company/catalitium-ai/ |
| X / Twitter | https://x.com/catalitium |
| Instagram | https://www.instagram.com/catalitium/ |
| YouTube | https://www.youtube.com/@Catalitium |
| TikTok | https://www.tiktok.com/@catalitium |
| Discord | https://discord.gg/6ZERxz9x |
| Telegram | https://t.me/catalitiumcareers |

### Files Modified
- `app/views/templates/base.html` — favicon fix, header grid, social icons
- `app/views/templates/landing.html` — SEO meta/H1, CTA links, subscribe trigger
