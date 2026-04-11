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

## 3. Git identity + Windows Git binary (this repo only)
- **Always** use the **Catalitium** org identity for commits here, not a personal GitHub name/email. Local author: `git config --local user.name` / `user.email` (see `.git/config`). Prefer the org GitHub **noreply** email from GitHub → Settings → Email when you want verified commits; until then defaults are **Catalitium** + **dev@catalitium.com**.
- **PATH:** Keeping `C:\Program Files\Git\mingw64\bin` on User or System `PATH` is fine (duplicate in both is harmless). Windows may still resolve `git` to `Git\cmd\git.exe` first; on older Git for Windows that can cause `error: unknown option 'trailer'` on `git commit`. This repo sets **Cursor/VS Code** `git.path` in [`.vscode/settings.json`](.vscode/settings.json) to **mingw64 `git.exe`**. In a plain terminal, use `"%ProgramFiles%\Git\mingw64\bin\git.exe"` or upgrade Git for Windows. Inspect PATH with [`scripts/check-git-path.ps1`](scripts/check-git-path.ps1).

## 4. Task Management (always in `tasks/todo.md`)
```markdown
## Plan
- [ ] Item 1 — success criteria
- [ ] Item 2 — ...

## Progress
- [x] Done item (with 1-line proof)

## Review
High-level changes + results + open questions