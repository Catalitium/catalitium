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

1. **One “how to run” path** — `README.md` + `run.py` + `.env.example` as the only entry narrative; delete scattered duplicate instructions.  
2. **Smaller hot files** — move new routes out of `factory.py` into `controllers/` as the default habit so the factory stays wiring-only.  
3. **Single task source** — either `tasks/todo.md` or GitHub issues, not both silently; reduces dropped context.  
4. **Script index** — one `scripts/README` table: purpose, required env, exit codes; stops guesswork before deploy.  
5. **Branch hygiene command** — document `git fetch && git branch --merged main` (and when to use `-D`) so merged feature branches do not linger.

### Top 5 — low-hanging fruit (simple enhancements)

1. **CI or `scripts/` one-liner** — `python -m compileall app && pytest tests -q` in docs or a tiny `Makefile`/`justfile` target.  
2. **Supabase checklist in repo** — bullet list: Site URL, redirect allowlist for `/auth/confirm`, email template sanity (link to `.env.example`).  
3. **404/redirect audit script** — extend existing smoke to assert removed routes (`/compare`) stay gone.  
4. **`.cursor/rules` + `claude-rules.md`** — keep them in sync with one line at top of each pointing to the other (already mirrored in `.mdc`).  
5. **Optional `pyvenv.cfg` note** — already in `run.py`; link from README “Troubleshooting” once.

### Top 5 — reconciliation (align divergent truths)

1. **`CLAUDE.md` vs `README.md`** — same feature list and stack version cues; one defers to the other for details.  
2. **Environment variables** — grep `os.getenv` / `environ` vs `.env.example`; missing keys documented.  
3. **Auth surfaces** — `/register`, `/auth/forgot`, `/auth/confirm`, `/auth/session` listed in one short doc section next to Supabase dashboard steps.  
4. **“Compare” naming** — salary `/salary/compare-cities` vs removed job `/compare` called out once to prevent accidental resurrection.  
5. **Git ignore vs tracked** — `.claude/` local only; `.cursor/rules/` tracked; no duplicate tracked secrets under ignored folders.

---

*Keep this file short. Prefer updating in-repo technical truth in `CLAUDE.md` / `README.md` and using this file for how agents should behave in this repo. Cursor loads [`.cursor/rules/catalitium-agents.mdc`](.cursor/rules/catalitium-agents.mdc) for the same behavior in-editor.*
