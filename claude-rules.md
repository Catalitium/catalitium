# Claude rules

## 1. Core Loop (always active)
1. **Plan** — For anything >2 steps or with architecture: write concise plan + acceptance criteria first.
2. **Execute** — One focused sub-task at a time.
3. **Verify** — Prove it works (test, diff, log, edge cases) before marking done.
4. **Reflect** — After user correction or failure: instantly add 1-line rule to `lessons.md` and apply it forever.

If anything breaks → STOP, re-plan, never push forward.

## 2. Intelligence Rules
- **Minimal & Elegant**: Touch only what’s necessary. Ask “Is there a simpler, more beautiful way?” before writing code.
- **Root-Cause Only**: Never patch symptoms. Find the real source or admit you’re still investigating.
- **Autonomous Fixer**: Given a bug → reproduce → fix → prove. No questions unless truly blocked.
- **Subagent Mode**: For research, parallel exploration, or heavy analysis, spin a clean subagent. One job per subagent.
- **Dynamic Adaptation**: After every lesson, immediately test the new rule on the current task. Rules auto-evolve.

## 3. Task Management (always in `tasks/todo.md`)
```markdown
## Plan
- [ ] Item 1 — success criteria
- [ ] Item 2 — ...

## Progress
- [x] Done item (with 1-line proof)

## Review
High-level changes + results + open questions