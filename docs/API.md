# Catalitium HTTP API

Base URL: `https://catalitium.com` (or your deployment `BASE_URL`).

## Authentication

Send your API key on every request:

- **Header (recommended):** `X-API-Key: cat_…`
- **Query (fallback):** `?api_key=cat_…`

Keys are issued after you subscribe to **API Access** (and confirm the key from email) or via **Register API key** in Studio.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/jobs` | Paginated job search (`title`, `country`, `page`, `per_page`) |
| `GET` | `/v1/jobs/<id>` | Single job by ID |
| `GET` | `/v1/salary` | Salary snapshot (`title` and/or `country` / location) |
| `GET` | `/api/keys/usage` | Usage counters for the authenticated key |

## Quotas

- **Free (confirmed key):** 50 requests per day and 500 per calendar month.
- **API Access (paid):** 10,000 requests per calendar month (with a high daily ceiling).

Rate-limit headers on success: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `X-RateLimit-Window`.

## Errors

| HTTP | `error` | Meaning |
|------|---------|---------|
| `401` | `invalid_key` | Missing, wrong, or inactive key |
| `429` | `quota_exceeded` | Daily or monthly limit (`window`: `daily` / `monthly`) |
| `404` | `not_found` / `no_data` | Resource or salary data not found |

## Example

```bash
curl -sS "https://catalitium.com/v1/jobs?per_page=5" \
  -H "X-API-Key: cat_your_key_here"
```

## Revoke a key

`DELETE /api/keys/me` with header `X-API-Key`.

---

More context and setup: **Studio → Developer API** after signing in at [catalitium.com/studio](https://catalitium.com/studio).
