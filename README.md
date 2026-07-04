# token_gateway_poc

A multi-provider **LLM API gateway** (OpenAI / Anthropic / Google Gemini
compatible) with a single `atp-…` key, a credit ledger, token metering, rate
limiting, and a minimal Vue console.

Point any provider SDK at this gateway by changing only the **base URL** and
**API key** — no wrapper library.

Design docs live in [`doc/`](./doc): how atptoken.ai works, how to build one,
and the [Phase 1/2 design & implementation plan](./doc/design-and-implementation.md).

## Stack

Python 3.12 · uv · FastAPI · httpx · SQLAlchemy 2 (async) · SQLite (default) /
Postgres · Vue 3 (CDN). Built test-first with pytest + respx.

> **DB note:** defaults to a local SQLite file so it runs with zero external
> services. Set `DATABASE_URL` to a `postgresql+asyncpg://…` DSN for production.

## Quickstart

```bash
uv sync --extra dev

# 1. Mint a workspace + project + key with 100 credits
uv run python scripts/create_key.py \
  --workspace "Acme" --project "prod" \
  --models gpt-5.4 claude-sonnet-4-6 gemini-2.5-pro \
  --credits 100
# -> prints an atp-… key AND the Workspace/Project IDs (save them)

# 2. Set the REAL upstream keys, then run the gateway
cp .env.example .env    # fill OPENAI_API_KEY etc.
uv run uvicorn gateway.main:app --reload

# 3. Console: open http://localhost:8000/  (admin token = ADMIN_TOKEN)
```

### Use it (only base URL + key change)

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="atp-...")
client.chat.completions.create(
    model="gpt-5.4", messages=[{"role": "user", "content": "hi"}]
)
```

```bash
curl http://localhost:8000/v1/models -H "Authorization: Bearer atp-..."
```

## Endpoints

| Endpoint | Compatible with |
|----------|-----------------|
| `GET /v1/models` | OpenAI (project allowlist) |
| `POST /v1/chat/completions` | OpenAI (+ streaming) |
| `POST /v1/messages` | Anthropic (+ streaming) |
| `POST /v1/models/{model}:generateContent` | Gemini |
| `GET/POST /admin/*` | Console API (X-Admin-Token) |
| `GET /` | Vue console |

Errors follow each SDK's shape: `400/401/402/403/429/502`.

## Tests

```bash
uv run pytest -q
```

## Phase map

- **Phase 1** — proxy, `atp-…` keys, credit ledger + metering, model allowlist,
  streaming, error contract, minimal console.
- **Phase 2** — orgs/users/memberships + roles, per-key rate limiting,
  payments/top-ups (mock + Stripe-ready), request logs + analytics, richer console.

See [`doc/design-and-implementation.md`](./doc/design-and-implementation.md).
