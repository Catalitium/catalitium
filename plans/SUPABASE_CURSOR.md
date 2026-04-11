# Connect Cursor to Supabase (plan)

Your Flask app already uses Supabase via **`.env`** (see [`.env.example`](../.env.example)). This plan adds **Cursor-native** access so the AI can reason against your real project (schema, SQL, logs) without pasting secrets into chat.

---

## What you already have in `.env` (keep using these for the app)

| Variable | Role |
|----------|------|
| `DATABASE_URL` | Postgres (Supabase pooler) — same DB the app uses |
| `SUPABASE_PROJECT_URL` | `https://<ref>.supabase.co` — Auth REST base |
| `SUPABASE_SECRET_KEY` | **Service role** JWT — server-only; never expose to browser or MCP if avoidable |

Do **not** put `SUPABASE_SECRET_KEY` into MCP or commit it.

---

## Path A — Official Supabase MCP (recommended for “native” Cursor)

Supabase exposes an **MCP server** so Cursor can list projects, run SQL (with guardrails), inspect schema, etc.

1. **Supabase account PAT**  
   In [Supabase Dashboard](https://supabase.com/dashboard) → **Account** → **Access Tokens** → create a **personal access token** (PAT). This is **not** the same as `SUPABASE_SECRET_KEY`; it authorizes the MCP client to your **account/projects**.

2. **Cursor MCP config** (local only — `.cursor/` is gitignored in this repo)  
   - Create folder: `catalitium/.cursor/`  
   - Create file: **`catalitium/.cursor/mcp.json`** (copy from example below).

   ```json
   {
     "mcpServers": {
       "supabase": {
         "command": "npx",
         "args": [
           "-y",
           "@supabase/mcp-server-supabase@latest",
           "--access-token",
           "YOUR_SUPABASE_PAT_HERE"
         ]
       }
     }
   }
   ```

   Replace `YOUR_SUPABASE_PAT_HERE` with the PAT. **Never commit this file.**

3. **Cursor UI**  
   **Settings → MCP** (or **Tools & MCP**) → confirm **supabase** server is enabled / green.

4. **Optional: tie MCP to the same project as `.env`**  
   Your `DATABASE_URL` host contains `postgres.<project-ref>` — use the same project in the Supabase dashboard when the MCP asks which project to scope.

**Docs:** [Supabase MCP](https://supabase.com/docs/guides/getting-started/mcp)

---

## Path B — Postgres MCP only (read-heavy, uses `DATABASE_URL`)

If you only want SQL against the DB and accept connection-string auth:

- Use a Postgres MCP server with **`DATABASE_URL`** from `.env` (session pooler URL).
- **Risk:** service credentials in MCP config; treat like production DB — prefer **read-only** DB role if Supabase allows a read replica or restricted user.

Use Path A unless you have a strong reason to wire raw Postgres.

---

## Path C — No MCP (minimal)

- Keep **`.env.example`** as documentation.
- In Cursor chat, say: “Project uses `DATABASE_URL` + `SUPABASE_PROJECT_URL` per `.env.example`; do not print secrets.”  
  You paste **non-secret** context (table names, error snippets) manually.

---

## Security checklist

- [ ] `.cursor/mcp.json` stays **local** (repo already ignores `.cursor/`).
- [ ] Never commit PAT or `SUPABASE_SECRET_KEY`.
- [ ] Rotate PAT if it leaks or a teammate leaves.
- [ ] Prefer Supabase MCP **project-scoped** operations over blanket admin where the UI allows.

---

## Rollout order (tonight)

1. Confirm `.env` has `DATABASE_URL`, `SUPABASE_PROJECT_URL`, `SUPABASE_SECRET_KEY` (app already works).
2. Create Supabase **PAT** → add **Path A** `mcp.json` → restart Cursor → verify MCP green.
3. Ask Cursor: “List tables in my Supabase project” (or equivalent MCP prompt) as a smoke test.
4. Optionally add a one-line note in your personal notes (not necessarily repo): which project ref matches production.

---

## Remote branch `feature/botwar`

Local branch **`feature/botwar`** was deleted. If a **remote** `origin/feature/botwar` still exists and you want it gone:

```bash
git push origin --delete feature/botwar
```

(Only if you are sure nobody else needs it.)
