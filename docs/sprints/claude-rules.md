# Catalitium — agent rules (sprint contract)

Use this file as **`@claude-rules.md`** before long or risky work. It complements `CLAUDE.md` (product/architecture) with **how** to change the repo.

## Before you ship

1. **Plan first** for any non-trivial change (3+ steps or structural impact). If something breaks tests or routes, **stop and replan** that slice.
2. **Default branch discipline**: feature work on a named branch (e.g. `feat/monolith-consolidation`). **Do not merge to `main`** without an explicit PR and human approval.
3. **Verify before “done”**: `python -m compileall app`, `pytest tests/`, and the relevant smoke section(s) from `python scripts/smoke.py --section …`.
4. **Prefer one canonical module** per concern (`app.utils` for shared helpers, `app.factory` for `create_app`, domain logic in `app/models/*`).
5. **Minimal diff**: touch only what the task needs; no drive-by refactors.

## Smoke entry point

From repo root:

```bash
python scripts/smoke.py --section routes
python scripts/smoke.py --section all
```

Sections: `db`, `routes`, `carl`, `supabase`, `smtp`, `reports`, `all`.

## After corrections

Append a dated line to `docs/sprints/feat-monolith-consolidation/lessons.md` (or the active sprint folder) with the mistake pattern and the fix.

## Elegance (balanced)

For non-trivial changes, ask whether a staff engineer would accept the diff. Skip bike-shedding on obvious one-liners.
