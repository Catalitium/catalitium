# Catalitium — agent rules (Claude / Cursor)

**Audience:** coding agents working in this repository.  
**Goal:** predictable quality, minimal surprise, and instructions that stay valid as the codebase evolves.

---

## 1. When to plan vs. execute

- **Plan first** when the task is non-trivial: multiple steps, trade-offs, touching more than a few files, schema or auth changes, or anything that could conflict with existing architecture.
- **Re-plan** if requirements shift, discovery invalidates the plan, or execution hits repeated dead ends. Do not brute-force past structural uncertainty.
- **Plans are for verification too:** include how you will prove correctness (tests, commands, manual checks), not only what you will build.

---

## 2. Parallelism and context

- Prefer **focused sub-tasks** (separate exploration, searches, or mechanical refactors) over stuffing everything into one long reply when it reduces errors or speeds delivery.
- **One clear objective per delegated thread:** narrow prompts beat vague “look at everything.”
- **Re-integrate deliberately:** summarize findings back into the main thread; do not assume the user read side channels.

---

## 3. Learning loop (after corrections)

- When the user corrects a mistake or rejects an approach, capture the **pattern** (what went wrong, what to do instead), not only the patch.
- Prefer **durable rules** (short, testable statements) over long narratives.
- If the repo has `tasks/lessons.md` (or similar), append there; otherwise a one-line note in the active task file is enough.

---

## 4. Definition of done

- **Do not claim completion** without evidence: tests run, or a stated reason when tests are out of scope, plus compile/lint/smoke as appropriate for the change.
- When behavior is non-obvious, **state the verification** you ran (command or flow), not only “done.”
- For regressions, **compare intent vs. diff:** would a careful reviewer see risk, dead code, or missing edge handling?

---

## 5. Code quality bar

- **Simplicity over cleverness:** smallest diff that meets the requirement; avoid drive-by refactors.
- **Root cause over symptoms:** especially for bugs and flaky tests; avoid “fix” by silencing failures.
- **Elegance check (non-trivial work only):** ask once whether the structure is clear and consistent with surrounding code; skip meta-design for one-line fixes.

---

## 6. Bugs and incidents

- Treat a **repro or failing test** as the source of truth: read the error, trace the code, fix, re-run.
- **Default to autonomy:** only ask the user when blocked on secrets, product intent, or irreversible data operations.
- **CI and local checks:** fix failing checks you can reproduce without asking for permission to “try.”

---

## 7. Task hygiene (when using `tasks/`)

- If `tasks/todo.md` exists for the current effort: keep a **short plan** with checkable items; update status as you go.
- End with a **brief result summary** (what changed, how verified). Link or cite paths, not vague “updated stuff.”

---

## 8. Boundaries and safety

- **Minimal footprint:** touch only files and behavior required by the task.
- **No secrets in repo:** never commit keys, tokens, or real `.env` contents; use `.env.example` patterns only.
- **Destructive or irreversible actions** (force-push, mass delete, production data): require explicit user instruction.

---

## Suggested additions (optional, incorporate over time)

- **Stack pin:** one paragraph pointing to canonical docs in-repo (`README.md`, `CLAUDE.md`, `pytest.ini`) so agents do not re-derive stack from scattered files.
- **“Out of scope” list:** 3–5 bullets (e.g. no new auth providers, no framework migrations) to prevent silent scope creep.
- **Performance budget:** when a change touches hot paths (search, DB, templates), note expected latency or query budget in the task before optimizing.
- **Accessibility and i18n:** if the product cares, add one line: keyboard paths, semantic HTML, no user-visible placeholder copy in templates without review.
- **Telemetry and privacy:** when adding analytics or cookies, cite the consent/CMP approach and where events are defined so agents do not duplicate trackers.
- **Rollback note:** for migrations or flag flips, one sentence on how to revert or feature-flag off.
- **Owner / escalation:** who to ask for product ambiguity (even a role name) when the user is offline.

---

## Retrospective (executive)

**What went well**  
We landed substantive refactors and product changes (MVC layout, compare removal, password-reset flow) while keeping automated tests green and documenting operational steps such as Supabase redirect URLs.  
The team converged on a single primary branch and shared rules so agents and humans align on verification and minimal diffs.

**What went wrong**  
Parallel worktrees and long-lived local `main` drift produced painful merges and duplicate file states until history was reconciled with `origin/main`.  
A broken local `.venv` and short-lived import experiments created noise in the working tree and risked shadowing real packages.

**What could have been done better**  
Treat **`origin/main` after merge** as the integration line immediately: fetch, merge or reset, then branch for experiments—never stack uncommitted refactors on a moving base.  
Keep a one-page **release checklist** (env, redirects, smoke commands) checked before declaring “done” so ops steps are not rediscovered under pressure.

---

## Flywheel — next time

### Top 5 — optimization by simplification

1. **`jobs.py` (≈1,800 LOC)** is the new `app.py` — routes, query helpers, guest tracking, sitemap, and robots.txt in one file. Split into `jobs_core.py` (landing + listings), `jobs_api.py` (api_* endpoints), `jobs_forms.py` (subscribe / contact / posting).
2. **`catalog.py` (≈1,650 LOC)** — career-tools bloc (`compute_ai_exposure`, `compute_market_position`, `get_career_paths`, `get_hiring_velocity`) is ≈300 LOC of unrelated concern; extract to `models/career_tools.py`.
3. **`identity.py` (≈528 LOC)** spans 4 unrelated domains: subscribers, contact forms, API keys, Stripe subscriptions. Split each into its own focused module under `models/`.
4. **DB error-handling inconsistency** — `identity.py`/`money.py` return `”ok”/”error”` strings; `catalog.py` raises exceptions. Pick one pattern (prefer exceptions) and standardise across all models.
5. **`api_ok`/`api_fail` vs `api_error_response`/`api_success_response`** — two tiers for the same thing. Controllers should use only the Flask-aware pair; remove the dict-only layer from `__all__`.

### Top 5 — low-hanging fruit (simple enhancements)

1. **`now_iso()` precision** — `utils.py` emits full ISO (no `timespec`), but old callers used `timespec=”seconds”`. Align to one format and document the choice.
2. **`models/__init__.py` is empty** — add `__all__` listing public callables, for discoverability parity with `controllers/__init__.py`.
3. **`deploy.txt` at root** — orphaned deployment notes not linked from anywhere. Absorb useful parts into `README.md` and delete.
4. **`app/__init__.py` is empty** — add a one-line docstring so bare package imports are self-documenting.
5. **`tests/smoke_prod.ps1`** — last PowerShell file in the repo. Document the equivalent bash/python invocation in a comment, or convert to a cross-platform Python script.

### Top 5 — Next things to-do (align divergent truths)

1. **`jobs.py` alias** — `_guest_daily_remaining = guest_daily_remaining` is a backward-compat alias. Remove it once all call sites in the file use the public name directly.
2. **SMTP smoke test coverage** — `utils.py` now owns all SMTP logic (merged from `mailer.py`); confirm `tests/smtp_smoke_test.py` still hits the right code path.
3. **Weekly digest entry-point** — `run_weekly_digest()` lives in `utils.py` with no documented cron command. Add invocation to `README.md`: `python -c “from app.utils import run_weekly_digest; import sys; sys.exit(run_weekly_digest())”`.
4. **`validate_market_reports` entry-point** — update any CI or cron reference still pointing at the deleted `scripts/validate_market_reports.py` to call `from app.utils import validate_market_reports` instead.
5. **Stash hygiene** — `git stash list` has 3 old WIP stashes; pop or drop them so future `stash pop` cannot resurface abandoned route/service experiments.

---

*Keep this file short. Prefer updating in-repo technical truth in `CLAUDE.md` / `README.md` and using this file for how agents should behave in this repo. Cursor loads [`.cursor/rules/catalitium-agents.mdc`](.cursor/rules/catalitium-agents.mdc) for the same behavior in-editor.*
