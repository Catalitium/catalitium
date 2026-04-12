# Final report: Item 2c (Carl + market research + REPORTS)

**Branch:** `feat/monolith-consolidation`  
**Date:** 2026-04-11  

## Summary

Market research catalog data, CV extraction, and all Carl / market-research HTTP routes were moved out of `app/factory.py` into dedicated modules and a `carl` blueprint. URLs are unchanged; Flask endpoint names are now namespaced as `carl.*`.

## What changed

| Area | Change |
|------|--------|
| **Data** | `REPORTS` list lives in `app/market_reports_data.py`; `factory.py` imports it for sitemap generation only. |
| **CV parsing** | `app/integrations/cv_extract.py` removed; logic is `app/models/cv.py`. Smoke script imports `app.models.cv`. |
| **Routes** | New `app/controllers/carl.py` (`carl_bp`): `/resources` (301), `/market-research`, `/market-research/<slug>`, `/troy`, `/carl`, `/carl/analyze`, `/carl/chat`. |
| **Rate limits** | `carl_analyze` / `carl_chat` limits (`20` / `40` per minute) applied in `create_app` after blueprint registration by wrapping `app.view_functions["carl.carl_analyze"]` and `...carl_chat` when Flask-Limiter is present. |
| **Templates** | `url_for` / `request.endpoint` updated from bare names to `carl.market_research_index`, `carl.market_research_report`, `carl.carl_dashboard`, `carl.resources`. |
| **Tests** | Carl fixtures monkeypatch `app.controllers.carl.upsert_profile_cv_extract` (patch where used). |
| **Scripts** | `scripts/validate_market_reports.py` loads `REPORTS` from `app.market_reports_data` via `sys.path` + import. |

## Verification

- `python -m pytest tests/` — **186 passed**, 2 skipped.  
- `python scripts/smoke.py --section routes` — **OK**.  
- `python scripts/validate_market_reports.py` — may exit non-zero if local `app/static/reports` PDFs or `pdf_path` entries do not match the validator rules (baseline data issue, not routing).

## Endpoint migration (for operators)

| Old endpoint | New endpoint |
|--------------|----------------|
| `resources` | `carl.resources` |
| `market_research_index` | `carl.market_research_index` |
| `market_research_report` | `carl.market_research_report` |
| `carl_dashboard` | `carl.carl_dashboard` |
| `troy_redirect_carl` | `carl.troy_redirect_carl` |

## Follow-ups (not in this commit)

- Item 2a / 2b: further `factory.py` slices (auth, jobs) per `AGENTS_PARALLEL.md` single-writer discipline.  
- Optional: relax or split `validate_market_reports.py` rules for gated HTML-only reports if product accepts empty `pdf_path`.
