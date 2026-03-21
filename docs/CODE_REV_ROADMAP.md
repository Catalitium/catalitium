# Code review roadmap

**Purpose:** Actionable backlog aligned with [claude-rules.md](../claude-rules.md) (plan → execute → verify; minimal, root-cause) and Catalitium’s search-first, high-signal mission. Horizon: **mostly 0–4 week quick wins**; items marked **(medium)** or **(large)** where appropriate.

**Grounded in:** `app/app.py`, `app/models/db.py`, `app/views/templates/base.html`, `app/views/templates/index.html`, `app/static/js/main.js`, `app/static/css/styles.css`, `app/static/js/sw.js`.

---

## Enhancements (15)

1. **Sticky search + results anchor** — Keep “jump to results” and visible result count in sync after client-side updates; reduces scroll confusion on mobile. **Impact:** Faster path from query to listings. **Effort:** S. **Area:** UI/UX. **Files:** `app/views/templates/index.html`, `app/static/js/main.js`.
2. **Empty-state playbook** — When `count == 0`, show suggested alternate titles/countries and a one-click “broaden search” (clear one filter). **Impact:** Fewer dead-ends on no-hit queries. **Effort:** S. **Area:** UI/UX. **Files:** `app/views/templates/index.html`, search route in `app/app.py`.
3. **Job card apply flow clarity** — Ensure apply/subscribe modal (`#jobModal`) always exposes errors inline and success next steps (check email). **Impact:** Higher trust on apply/subscribe. **Effort:** S. **Area:** UI/UX. **Files:** `app/views/templates/base.html`, `app/static/js/main.js`.
4. **Salary intel on cards** — Surface parsed salary band + delta badge consistently where data exists (with “estimate” labeling). **Impact:** Core value prop without opening detail. **Effort:** M **(medium)**. **Area:** UI/UX + backend/data. **Files:** job list partials in `index.html`, `app/salary_utils.py` (if present), route context in `app/app.py`.
5. **Keyboard search affordance** — Document/focus `/` or `Ctrl+K` to focus `#q` (progressive enhancement; no break without JS). **Impact:** Power-user speed. **Effort:** S. **Area:** UI/UX. **Files:** `app/static/js/main.js`, `index.html` hint text.
6. **Auth session recovery copy** — When Supabase auth is unavailable, user-facing message should suggest refresh + status, not generic failure. **Impact:** Less support churn. **Effort:** S. **Area:** UI/UX + backend/data. **Files:** `app/app.py` (`_get_supabase*`, flash handlers).
7. **Profile / hire onboarding** — Guided checklist for recruiter/company fields (`_HIRE_FIELDS`) with validation messages next to fields. **Impact:** Completer hire funnel. **Effort:** M **(medium)**. **Area:** UI/UX. **Files:** hire templates + `app/app.py` profile routes.
8. **Weekly digest transparency** — Subscription confirmation UI states frequency, opt-out, and data use (link to `/legal`). **Impact:** Privacy-aligned growth. **Effort:** S. **Area:** UI/UX. **Files:** `base.html` / subscription modal templates, `app/app.py`.
9. **Ghost job badge explainer** — Tooltip or “Learn more” already partially in copy; add short mobile-friendly drawer instead of wall of text. **Impact:** Trust without clutter. **Effort:** S. **Area:** UI/UX. **Files:** `app/views/templates/index.html`.
10. **AI summary opt-in UX** — If AI summaries are optional/costly, explicit toggle + loading skeleton + “unavailable” state when API degrades. **Impact:** Predictable behavior. **Effort:** M **(medium)**. **Area:** UI/UX + backend/data. **Files:** `app/static/js/ai_summary.js` (if used), `app/app.py` API handlers.
11. **Cookie consent + analytics** — Ensure statistics/marketing scripts respect Cookiebot categories; add dev-only bypass for local testing. **Impact:** Compliance + faster local dev. **Effort:** S–M. **Area:** UI/UX + platform. **Files:** `app/views/templates/base.html`.
12. **PWA install hint** — After repeat visits, soft prompt for “Add to Home Screen” where `manifest.json` + SW exist. **Impact:** Return traffic. **Effort:** S. **Area:** UI/UX. **Files:** `app/static/js/main.js`, `app/static/manifest.json`.
13. **Print / share job view** — Reuse print CSS in `base.html` for job detail/report pages so shared prints hide ads/chrome. **Impact:** Professional sharing. **Effort:** S. **Area:** UI/UX. **Files:** `base.html`, job detail template.
14. **Rate-limit friendly errors** — When Flask-Limiter triggers, return JSON/HTML message with retry guidance (not blank 429). **Impact:** Less confusion on hot actions. **Effort:** S. **Area:** backend/data. **Files:** `app/app.py` (Limiter config).
15. **Health endpoint visibility** — `/health` already checks DB; expose optional `GET /health?deep=1` for migrations check **(medium)** or keep simple and document for deploy probes only. **Impact:** Safer rollouts. **Effort:** S–M. **Area:** backend/data. **Files:** `app/app.py`.

---

## Simplifications (15)

1. **Tailwind strategy** — Either commit to CDN + critical inline overrides, or move to built CSS; reduce duplicate “fallback” rules that overlap Tailwind utilities. **Impact:** One styling story. **Effort:** M **(medium)**. **Area:** UI/UX. **Files:** `base.html`, `app/static/css/styles.css`.
2. **Favicon / icon tags** — Consolidate multiple favicon links (PNG + inline SVG) to one coherent set to avoid conflicting browser picks. **Impact:** Less head noise. **Effort:** S. **Area:** UI/UX. **Files:** `app/views/templates/base.html`.
3. **Single CSRF contract** — Standardize on meta `csrf-token` + hidden fields for every mutating form; audit JSON `fetch` callers to always send token. **Impact:** Fewer `invalid_csrf` surprises. **Effort:** M. **Area:** backend/data + UI/UX. **Files:** `app/app.py`, `app/static/js/main.js`, templates.
4. **Overlay close pipeline** — `closeUiOverlays` already centralizes behavior; ensure all modals/dialogs register only this path (no duplicate listeners). **Impact:** Less stuck-scroll / grey screen bugs. **Effort:** S. **Area:** UI/UX. **Files:** `app/static/js/main.js`.
5. **Supabase client split** — Document why `_get_supabase` vs `_get_supabase_admin` exists; ensure no third code path unless necessary. **Impact:** Easier auth debugging. **Effort:** S. **Area:** backend/data. **Files:** `app/app.py`.
6. **Environment matrix** — Table in README: `DATABASE_URL` / `SUPABASE_URL`, `SUPABASE_PROJECT_URL`, `SUPABASE_SECRET_KEY`, `SECRET_KEY`, pool vars — one canonical order. **Impact:** Fewer misconfigured deploys. **Effort:** S. **Area:** platform. **Files:** `README.md`, `app/models/db.py`.
7. **DB URL normalization** — `_normalize_pg_url` already strips `pgbouncer`; add comment + test fixtures for typical Supabase strings so future edits don’t regress. **Impact:** Stable connections. **Effort:** S. **Area:** backend/data. **Files:** `app/models/db.py`.
8. **Remove tracked bytecode** — Ensure `__pycache__` and `*.pyc` are gitignored and stripped from history going forward. **Impact:** Cleaner diffs. **Effort:** S. **Area:** platform. **Files:** `.gitignore`.
9. **Third-party scripts in dev** — Gate Cookiebot/AdSense/analytics behind `FLASK_ENV` or explicit flag so local work is faster and offline-friendly. **Impact:** Faster iteration. **Effort:** S. **Area:** UI/UX. **Files:** `app/views/templates/base.html`, `app/app.py`.
10. **Duplicate modal patterns** — `createFormModal` pattern vs one-off dialogs: migrate stragglers to shared helper. **Impact:** Less JS branching. **Effort:** M **(medium)**. **Area:** UI/UX. **Files:** `app/static/js/main.js`.
11. **Cache header policy** — Centralize `after_request` Cache-Control rules in one function with comments per response type. **Impact:** Easier reasoning about SW vs HTML. **Effort:** S. **Area:** backend/data. **Files:** `app/app.py`.
12. **Service worker scope** — `sw.js` only intercepts `/static/`; document that HTML is always network-first to avoid stale shell confusion. **Impact:** Fewer “old UI” reports. **Effort:** S. **Area:** UI/UX + platform. **Files:** `app/static/js/sw.js`, `README.md`.
13. **API error shape** — Unify `_api_error` / `jsonify({"error": ...})` keys (`code`, `message`) for client handling. **Impact:** One client parse path. **Effort:** M. **Area:** backend/data. **Files:** `app/app.py`, `app/api_utils.py`.
14. **Search route parameters** — Keep `title`/`country` query names consistent in forms, canonical URLs, and GTM events to reduce analytics fragmentation. **Impact:** Cleaner analytics. **Effort:** S. **Area:** UI/UX + backend/data. **Files:** `index.html`, `app/app.py`, `app/gtm_events.py` (if present).
15. **Stripe + webhook handlers** — Group Stripe routes and helpers in a submodule **(large)** only if `app.py` grows further; until then, TOC comment blocks in `app.py`. **Impact:** Navigation without full refactor. **Effort:** S–M. **Area:** backend/data. **Files:** `app/app.py`.

---

## Optimizations (5)

1. **HTTP compression** — `flask_compress` is already wired; verify production WSGI enables it and text/json responses benefit. **Impact:** Lower bandwidth, faster TTFB for HTML/JSON. **Effort:** S. **Area:** backend/data. **Files:** `app/app.py`, deployment config.
2. **Static asset cache busting** — Long `max-age` for `/static/` with `immutable` where safe; ensure deploys version `sw.js` `CACHE` name (already `catalitium-v4`) on each release. **Impact:** Fewer stale SW caches. **Effort:** S. **Area:** UI/UX + platform. **Files:** `app/app.py` (`after_request`), `app/static/js/sw.js`.
3. **Postgres pool tuning** — `DB_POOL_MAX` + `statement_timeout` / `idle_in_transaction_session_timeout` are set; monitor pool exhaustion under load and adjust `max_size` vs Gunicorn workers. **Impact:** Fewer 503s under burst. **Effort:** M **(medium)**. **Area:** backend/data. **Files:** `app/models/db.py`, Gunicorn settings.
4. **Limiter coverage audit** — Confirm high-cost endpoints (auth, AI, Stripe webhooks) have appropriate limits; avoid throttling public GET job search. **Impact:** Abuse resistance without hurting SEO traffic. **Effort:** S. **Area:** backend/data. **Files:** `app/app.py`.
5. **Structured logging** — Correlate request id (`api_utils.generate_request_id`) with DB duration and upstream failures in logs for `/health` and API routes. **Impact:** Faster incident triage. **Effort:** M. **Area:** backend/data. **Files:** `app/app.py`, `app/api_utils.py`.

---

## References

- Project mission & stack: [CLAUDE.md](../claude.md), [README.md](../README.md).
- Working agreements: [claude-rules.md](../claude-rules.md).

*Branch: `code-rev` — doc added for planning only; implement items in separate focused commits.*
