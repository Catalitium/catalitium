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
