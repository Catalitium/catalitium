## Planning and Scope Rules

- Never implement infra-heavy additions (Redis, billing, complex auth) without explicit approval and business justification.
- Keep enhancements incremental: reliability first, then performance, then feature additions.
- If plan/implementation drift appears, stop and restate scope in 5-10 lines before continuing.

## API Change Rules

- Do not ship new API routes without normalized error contracts (`code`, `message`, `request_id`).
- Reuse existing DB write paths (`insert_contact`, `insert_subscriber`) before adding new tables.
- Keep versioned routes thin wrappers over shared logic to avoid split behavior.

## Operational Rules

- Preserve unrelated user changes by working in a clean branch/worktree when the current branch is dirty.
- Validate syntax and lints before handoff; run full endpoint smoke tests only when DB env is configured.
- Never commit `.env` or secret-bearing files.
