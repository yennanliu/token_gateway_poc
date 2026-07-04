# Design & Implementation Doc — Token Gateway (Phase 1)

> Companion to [`how-atptoken-works.md`](./how-atptoken-works.md) and
> [`how-to-build-a-token-gateway.md`](./how-to-build-a-token-gateway.md).
> Concrete implementation design for a **Python + uv** MVP.
> Compiled: 2026-07-05

This is the actionable design: what to build in Phase 1, the exact tech stack,
project layout, and step-by-step implementation order. **Guiding principle:
keep the first phase simple.** No microservices, no queues, no warehouse —
one Python service + Postgres.

---

## 1. Scope

### In scope (Phase 1)
- A single FastAPI service acting as an **OpenAI-compatible proxy** to real
  providers.
- `atp-…` API keys (hashed at rest).
- Token metering + a **credit ledger** in Postgres (debit on each request).
- Streaming pass-through.
- Core endpoints: `GET /v1/models`, `POST /v1/chat/completions`,
  `POST /v1/messages` (Anthropic), `:generateContent` (Gemini).
- Per-project model allowlist.

### Out of scope (later phases)
- Web console / dashboards (manage via SQL / admin CLI in Phase 1).
- Payments (Stripe) — top-ups done manually via a script.
- Rate limiting, request-log UI, analytics warehouse.
- Format *translation* between providers (Phase 1 is pass-through per provider).

---

## 2. Tech stack (Phase 1)

| Concern | Choice | Why |
|---------|--------|-----|
| Language | **Python 3.12** | simple, familiar, good SDKs |
| Package/env manager | **uv** | fast, single tool for venv + deps + run |
| Web framework | **FastAPI** | async, streaming, typed, easy |
| ASGI server | **uvicorn** | standard for FastAPI |
| HTTP client (upstream) | **httpx** (async) | streaming support |
| DB | **Postgres** | ledger needs transactions |
| DB access | **SQLAlchemy 2.0 (async)** + **asyncpg** | typed models, migrations-ready |
| Migrations | **Alembic** | schema evolution |
| Config | **pydantic-settings** | env-based config |
| Hashing | **hashlib (SHA-256)** | key hashing (Phase 1) |
| Tests | **pytest** + **respx** | mock upstream HTTP |

Keep dependencies minimal. Everything runs as **one process**.

---

## 3. Project layout

```
token_gateway_poc/
├── pyproject.toml            # uv-managed deps + project metadata
├── uv.lock
├── .env                      # secrets (gitignored)
├── alembic/                  # migrations
├── src/
│   └── gateway/
│       ├── __init__.py
│       ├── main.py           # FastAPI app + route registration
│       ├── config.py         # pydantic-settings (upstream keys, DB url)
│       ├── db.py             # async engine + session
│       ├── models.py         # SQLAlchemy models (orgs, keys, ledger, usage)
│       ├── auth.py           # extract + hash + resolve api key -> project
│       ├── pricing.py        # model -> (in_rate, out_rate) table
│       ├── billing.py        # debit ledger atomically
│       ├── usage.py          # token counting / usage extraction
│       ├── routers/
│       │   ├── models.py     # GET /v1/models
│       │   ├── openai.py     # POST /v1/chat/completions
│       │   ├── anthropic.py  # POST /v1/messages
│       │   └── gemini.py     # POST /v1/models/{model}:generateContent
│       └── providers/
│           ├── base.py       # adapter interface
│           ├── openai.py     # forward to api.openai.com
│           ├── anthropic.py  # forward to api.anthropic.com
│           └── gemini.py     # forward to generativelanguage.googleapis.com
├── scripts/
│   ├── create_key.py         # admin: mint a key for a project
│   └── topup.py              # admin: add credits to a workspace
└── tests/
```

---

## 4. Data model (Phase 1)

Same hierarchy as the design doc, trimmed for the MVP. Money is stored as
**integer micro-credits** (`1 credit = $0.01`, so `1 micro-credit = $0.00000001`;
or simpler: store `credit_micros` where `1_000_000 micros = 1 credit`).

```sql
CREATE TABLE workspaces (
  id            UUID PRIMARY KEY,
  name          TEXT NOT NULL,
  credit_micros BIGINT NOT NULL DEFAULT 0     -- balance
);

CREATE TABLE projects (
  id           UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES workspaces(id),
  name         TEXT NOT NULL
);

CREATE TABLE project_models (
  project_id UUID NOT NULL REFERENCES projects(id),
  model_id   TEXT NOT NULL,
  PRIMARY KEY (project_id, model_id)          -- presence = enabled
);

CREATE TABLE api_keys (
  id          UUID PRIMARY KEY,
  project_id  UUID NOT NULL REFERENCES projects(id),
  key_prefix  TEXT NOT NULL,                  -- 'atp-' + first 8 chars (display)
  key_hash    TEXT NOT NULL UNIQUE,           -- sha256(raw key)
  revoked_at  TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE usage_events (
  id            UUID PRIMARY KEY,
  api_key_id    UUID NOT NULL REFERENCES api_keys(id),
  project_id    UUID NOT NULL REFERENCES projects(id),
  model_id      TEXT NOT NULL,
  input_tokens  INT NOT NULL,
  output_tokens INT NOT NULL,
  cost_micros   BIGINT NOT NULL,
  status        INT NOT NULL,                 -- HTTP status
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ledger_entries (
  id           UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES workspaces(id),
  delta_micros BIGINT NOT NULL,               -- negative = spend, positive = topup
  reason       TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

(Organizations, users, memberships, and roles are deferred to the console phase.)

---

## 5. Request lifecycle (per call)

```
1. Receive request on a provider path (e.g. /v1/chat/completions)
2. auth: read key from Authorization / x-api-key / x-goog-api-key / ?key=
        -> sha256 -> look up api_keys -> project -> workspace
        -> 401 if missing/unknown/revoked
3. quota: if workspace.credit_micros <= 0 -> 402
4. allowlist: requested model in project_models? else -> 403
5. adapter: strip client key, inject real upstream key, rewrite host,
            forward body (stream if requested) via httpx
6. meter: read usage from provider response (prompt/completion tokens)
7. bill: cost = in_tokens*in_rate + out_tokens*out_rate (micros)
         in ONE transaction:
           - insert usage_event
           - insert ledger_entry(delta = -cost)
           - update workspaces.credit_micros -= cost
8. return provider response to client (in the SDK's expected shape)
```

For **streaming**, steps 6–7 run when the stream closes (accumulate usage from
the final chunk / SSE `usage` field; bill on close even if the client
disconnects).

---

## 6. Key design decisions

- **Pass-through, not translation.** In Phase 1, the OpenAI path forwards to
  OpenAI, Anthropic path to Anthropic, Gemini path to Gemini. We do **not**
  translate one format to another. This removes the hardest part and still gives
  a working multi-provider gateway (client picks the SDK matching the model).
- **Trust upstream `usage`.** Rather than tokenizing ourselves, read the token
  counts the provider returns. Simpler and accurate. (Add local tokenization
  later only if a provider omits usage on streaming.)
- **One process, sync-simple billing.** Debit synchronously in the request path
  inside a DB transaction. No queue. Correctness over throughput in Phase 1.
- **SHA-256 key hashing.** Fast lookup by hash. (Argon2 is overkill for
  high-entropy random keys; revisit if keys ever become low-entropy.)
- **Micro-credits as BIGINT.** Never floats for money.

---

## 7. Implementation steps (ordered, each testable)

### Step 0 — Project scaffold
```bash
uv init
uv add fastapi uvicorn httpx "sqlalchemy[asyncio]" asyncpg alembic pydantic-settings
uv add --dev pytest respx
```
Create the `src/gateway/` layout above. `uv run uvicorn gateway.main:app --reload`
should serve a `/health` endpoint.

### Step 1 — Bare OpenAI proxy (no auth, no billing)
- Implement `POST /v1/chat/completions` → forward verbatim to
  `https://api.openai.com/v1/chat/completions` with a hardcoded key from `.env`.
- **Verify:** point the real OpenAI Python SDK at `base_url=http://localhost:8000/v1`
  and get a completion. This is the whole thesis proven.

### Step 2 — Database + models
- Add `db.py`, `models.py`, Alembic migration for the tables in §4.
- `scripts/create_key.py`: create a workspace, project, and one `atp-…` key;
  print the raw key once.

### Step 3 — Authentication
- `auth.py`: FastAPI dependency that extracts the key from any accepted location,
  hashes it, resolves project/workspace, returns a context object.
- Return `401` on failure. Wire it into the chat route.

### Step 4 — Metering + credit ledger
- `pricing.py`: static dict of `model -> (in_rate_micros, out_rate_micros)`.
- After a (non-streaming) response, extract `usage`, compute cost, and in one
  transaction insert `usage_event` + `ledger_entry` and decrement balance.
- Add the `credit_micros <= 0 → 402` check before forwarding.
- `scripts/topup.py`: add credits (positive ledger entry).
- **Verify:** balance goes down by the right amount after a call; `402` at zero.

### Step 5 — Model allowlist
- Check requested `model` against `project_models`; `403` if absent.

### Step 6 — Streaming
- Use `httpx` streaming + FastAPI `StreamingResponse` to pass SSE through.
- Meter/bill on stream close (parse usage from the terminal chunk).
- **Verify:** streamed completion works and is billed.

### Step 7 — Add Anthropic + Gemini adapters
- `POST /v1/messages` → `api.anthropic.com` (Anthropic streaming events).
- `POST /v1/models/{model}:generateContent` → Gemini host, accept
  `x-goog-api-key`.
- `GET /v1/models` → return the union of enabled models for the project.
- **Verify:** each provider's official SDK works by only changing base URL + key.

### Step 8 — Error contract & polish
- Map failures to `400/401/402/403/429/502/503` in the shape each SDK expects.
- Structured logging of every request (key id, model, tokens, status, latency).

---

## 8. Definition of done (Phase 1)

- [ ] OpenAI, Anthropic, and Gemini official SDKs all work against the gateway
      by changing only base URL + `atp-…` key.
- [ ] Requests are authenticated by hashed key → project.
- [ ] Streaming works for all three.
- [ ] Every request debits the workspace balance correctly and atomically.
- [ ] `402` at zero credits; `403` for disabled models; `401` for bad keys.
- [ ] Admin scripts can mint keys and top up credits.
- [ ] Tests cover auth, billing math, allowlist, and one proxy path (respx-mocked).

---

## 9. Phase 2+ (later, not now)

- Web console (Next.js) for keys, dashboards, top-ups.
- Stripe payments.
- Redis rate limiting + per-key quotas.
- Org/user/membership + roles (Owner/Admin/Member).
- Request-log UI + analytics (ClickHouse/BigQuery).
- Optional cross-provider format translation.

---

## Summary

Phase 1 is a **single FastAPI service (Python + uv) + Postgres** that proxies
OpenAI/Anthropic/Gemini via pass-through, authenticates hashed `atp-…` keys,
meters tokens from upstream usage, and debits an integer credit ledger inside one
transaction per request. Build it in eight verifiable steps, starting from a
hardcoded bare proxy and layering auth → billing → allowlist → streaming →
multi-provider. Consoles, payments, and rate limiting come in Phase 2.
