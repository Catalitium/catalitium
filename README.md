# Catalitium

## Soul

Move fast. Stay lean. Let software do the heavy lifting.
Automation over complexity. Outcomes over effort. Intelligence over headcount.
Direct. Honest. Efficient.

## Mission

Companies waste money on overcomplicated solutions.
Talent doesn't know what they're worth. Job markets are a black box.
We build lean tools that connect people with what they need to grow — faster, cheaper, smarter.
We remove the noise so people can focus on what matters.

## Vision

Every company gets the tools they need, regardless of size or budget.
Every professional knows their market value and how to improve it.
AI and software handle the heavy lifting so humans do the meaningful work.

### API Access

Signed-in users can register a free API key at `POST /api/keys/register`.
Once activated via email, use the key as a header on all `/v1/` endpoints:

```bash
curl https://catalitium.com/v1/jobs?title=python \
  -H "X-API-Key: cat_your_key_here"
```

**Endpoints**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/jobs` | Search jobs (params: `title`, `country`, `page`) |
| `GET` | `/v1/jobs/<id>` | Single job detail |
| `GET` | `/v1/salary` | Salary lookup by title + country |
| `GET` | `/api/keys/usage` | Daily quota and reset time |

Free tier: **50 requests/day** · Reset: UTC midnight

---
