# Quick wins (keep it simple)

## Top 5 — simple low-hanging fruit still worth doing

1. **Replace Tailwind CDN with a built CSS file** — Biggest perceived win long-term (smaller download, no runtime JIT). Not a one-liner; schedule when you touch styling anyway.
2. **Nginx (or your reverse proxy) `gzip` + long cache for `/static/`** — Lets the edge do cheap work; pair with `ASSET_VERSION` bumps on deploy (already in templates for JS/CSS).
3. **Turn up Gunicorn workers** — e.g. `(2 × CPU cores) + 1` and a sane thread count; watch DB pool `DB_POOL_MAX` so you don’t exhaust Postgres.
4. **DB indexes on hot filters** — If `Job.search` filters on columns that aren’t indexed, add indexes in Supabase (one migration when you confirm slow queries).
5. **Rate-limit storage in Redis** — `RATELIMIT_STORAGE_URI=redis://...` in prod so limiter isn’t in-memory per worker (stops weirdness under multi-worker).

---

## Top 5 — simple, “quick & dirty” speed levers (mostly not code)

These target **TTFB**, **CPU on the Flask process**, and **bytes over the wire** — without new architecture.

1. **Don’t hash huge HTML for ETag** — Implemented: ETag only when HTML body ≤ 64KB (avoids MD5 on every request for fat pages).
2. **Cache-bust static CSS** — Implemented: `styles.css` and `manifest.json` use `?v=asset_version` so browsers can keep `immutable` cache safely across deploys.
3. **Skip tiny gzip** — Implemented: `COMPRESS_MIN_SIZE` = 1024 so Flask-Compress doesn’t spend time compressing tiny responses.
4. **Defer non-critical images** — Implemented: footer logo uses `loading="lazy"` (header logo stays eager).
5. **Production process** — Run with `ENV=production`, `FLASK_DEBUG=0`, and enough Gunicorn workers; put Nginx gzip on for HTML/JSON if not already.

**Reality check:** The **Tailwind CDN script** is still the heaviest front-end cost; the real fix is a compiled CSS build — listed above as #1, not a one-hour hack.
