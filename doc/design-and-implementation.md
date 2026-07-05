# Design & Implementation Doc — Token Gateway (Phase 1)

> Companion to [`how-atptoken-works.md`](./how-atptoken-works.md) and
> [`how-to-build-a-token-gateway.md`](./how-to-build-a-token-gateway.md).
> Concrete implementation design for a **Python + uv** MVP.
> Compiled: 2026-07-05

This is the actionable design: what to build in Phase 1, the exact tech stack,
project layout, and step-by-step implementation order. **Guiding principle:
keep the first phase simple.** No microservices, no queues, no warehouse —
one Python service + Postgres.

**Methodology: Test-Driven Development (TDD).** Every step below is written
**test-first** — we write a failing test that specifies the behavior, then write
the minimum code to make it pass, then refactor. Red → Green → Refactor. No
production code is written without a failing test that demands it.

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
- A **minimal console UI**: a single static `index.html` using **Vue.js (via
  CDN)** that shows the workspace credit balance, lists API keys, and shows
  recent usage — read-only, talking to a few small admin JSON endpoints.

### Out of scope (later phases)
- A full SPA console / build pipeline (Phase 1 is one static HTML file, no build
  step).
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
| Tests | **pytest** + **pytest-asyncio** + **respx** + **httpx** test client | TDD; mock upstream HTTP |
| Frontend | **Vue.js 3 via CDN** in one static `index.html` | no build step, simplest possible console |

Keep dependencies minimal. Everything runs as **one process**. The frontend is a
single HTML file served by FastAPI (or opened directly) — **no npm, no bundler**.

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
│       ├── providers/
│       │   ├── base.py       # adapter interface
│       │   ├── openai.py     # forward to api.openai.com
│       │   ├── anthropic.py  # forward to api.anthropic.com
│       │   └── gemini.py     # forward to generativelanguage.googleapis.com
│       └── admin.py          # small read-only JSON endpoints for the console
├── frontend/
│   └── index.html            # Vue 3 (CDN) console — balance, keys, usage
├── scripts/
│   ├── create_key.py         # admin: mint a key for a project
│   └── topup.py              # admin: add credits to a workspace
└── tests/                    # tests written FIRST, mirrors src/gateway/
    ├── conftest.py           # fixtures: test DB, async client, seeded key
    ├── test_auth.py
    ├── test_billing.py
    ├── test_allowlist.py
    ├── test_proxy_openai.py
    ├── test_streaming.py
    └── test_admin.py
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

## 7. TDD workflow

Every step follows the same loop:

1. **Red** — write a test in `tests/` that asserts the new behavior. Run it;
   watch it fail for the right reason (`uv run pytest tests/test_x.py -x`).
2. **Green** — write the minimum code in `src/gateway/` to make it pass.
3. **Refactor** — clean up while keeping the suite green.
4. Commit on green.

Test infrastructure (build this in Step 0, before any feature):
- `conftest.py` provides an **async test DB** (a throwaway Postgres schema or a
  transaction rolled back per test), an **httpx AsyncClient** bound to the ASGI
  app, and a **seeded fixture** (a workspace with credits + a project + one known
  `atp-…` key whose raw value the test knows).
- **respx** intercepts outbound calls to `api.openai.com` /
  `api.anthropic.com` / Gemini, so tests never hit real providers and can assert
  exactly what we forward (URL, injected key, body) and stub what comes back.

Rule: **no production code without a failing test that requires it.**

## 8. Implementation steps (ordered, TDD, each step = red→green→refactor)

### Step 0 — Scaffold + test harness
```bash
uv init
uv add fastapi uvicorn httpx "sqlalchemy[asyncio]" asyncpg alembic pydantic-settings
uv add --dev pytest pytest-asyncio respx
```
- Create the `src/gateway/` layout and `tests/conftest.py` fixtures above.
- **First test:** `test_health` — `GET /health` returns `200 {"status":"ok"}`.
  Red → implement the route → green. This proves the harness works.

### Step 1 — Bare OpenAI proxy (no auth, no billing)
- **Test first:** with respx stubbing `api.openai.com`, POST to
  `/v1/chat/completions` and assert the response is forwarded and the upstream
  received our real key + the same body.
- Then implement the forward-verbatim route.
- **End-to-end check (manual):** point the real OpenAI Python SDK at
  `base_url=http://localhost:8000/v1` and get a completion. This is the whole
  thesis proven.

### Step 2 — Database + models
- **Test first:** `test_models` — inserting a workspace/project/key and querying
  them back works; balance defaults to 0.
- Implement `db.py`, `models.py`, and the Alembic migration for §4.
- `scripts/create_key.py`: mint a workspace/project/`atp-…` key (print raw once).

### Step 3 — Authentication
- **Test first (`test_auth.py`):** valid key in each accepted location resolves
  to the right project; missing/unknown/revoked key → `401`.
- Implement `auth.py` dependency (extract → sha256 → resolve → context) and wire
  it into the chat route.

### Step 4 — Metering + credit ledger
- **Test first (`test_billing.py`):** given a stubbed upstream `usage`, after one
  call the `usage_event` + `ledger_entry` are written and
  `workspace.credit_micros` drops by exactly `in*in_rate + out*out_rate`. Also:
  balance ≤ 0 → `402` and no forward happens.
- Implement `pricing.py`, `billing.py` (atomic debit in one transaction), and the
  pre-forward balance check.
- `scripts/topup.py`: add credits (positive ledger entry).

### Step 5 — Model allowlist
- **Test first (`test_allowlist.py`):** enabled model → forwards; disabled model
  → `403` and no upstream call.
- Implement the `project_models` check.

### Step 6 — Streaming
- **Test first (`test_streaming.py`):** respx streams SSE chunks; assert the
  client receives them in order **and** billing runs on stream close (parse
  `usage` from the terminal chunk).
- Implement `httpx` streaming + FastAPI `StreamingResponse`; bill on close (even
  on client disconnect).

### Step 7 — Anthropic + Gemini adapters + model list
- **Test first:** a proxy test per provider (respx-stubbed) + `GET /v1/models`
  returns the union of the project's enabled models.
- Implement `/v1/messages` → `api.anthropic.com`,
  `/v1/models/{model}:generateContent` → Gemini (accept `x-goog-api-key`), and
  `GET /v1/models`.
- **End-to-end check:** each provider's official SDK works by changing only base
  URL + key.

### Step 8 — Error contract & polish
- **Test first:** each failure maps to `400/401/402/403/429/502/503` in the shape
  the calling SDK expects.
- Implement the error mapping + structured per-request logging (key id, model,
  tokens, status, latency).

### Step 9 — Minimal Vue.js console (`frontend/index.html`)
- **Test first (`test_admin.py`):** small read-only admin endpoints return JSON —
  e.g. `GET /admin/workspaces/{id}/summary` (balance + key list) and
  `GET /admin/projects/{id}/usage` (recent `usage_events`). Assert shape + that
  they require an admin token.
- Implement those endpoints.
- Build `frontend/index.html`: a single file loading **Vue 3 from a CDN** with an
  inline `fetch()`-based app that renders the credit balance, a table of API keys
  (prefix + created/revoked), and a recent-usage table. No build step; serve it
  as a static file from FastAPI. Keep styling minimal (a little inline CSS).
  Frontend is verified manually in the browser — no JS test framework in Phase 1.

---

## 9. Definition of done (Phase 1)

- [ ] Every feature was built test-first; the suite is green and covers auth,
      billing math, allowlist, streaming, one proxy path per provider, and the
      admin endpoints (all respx-mocked — no live provider calls in tests).
- [ ] OpenAI, Anthropic, and Gemini official SDKs all work against the gateway
      by changing only base URL + `atp-…` key.
- [ ] Requests are authenticated by hashed key → project.
- [ ] Streaming works for all three.
- [ ] Every request debits the workspace balance correctly and atomically.
- [ ] `402` at zero credits; `403` for disabled models; `401` for bad keys.
- [ ] Admin scripts can mint keys and top up credits.
- [ ] The Vue `index.html` console shows balance, keys, and recent usage.

---

## 10. Phase 2 (done)

- Organizations / users / memberships + roles (data model).
- Per-key rate limiting (in-memory token bucket).
- Payments / top-ups (mock mode + Stripe-ready path).
- Request logs + per-model analytics admin API.
- Single-file Vue 3 (CDN) console.

---

## 11. Phase 3 — Control plane, RBAC & migrations

Turn the admin-token-only surface into a real self-serve control plane.

**Scope**
- **Management API** (`/manage/*`) — CRUD for orgs, workspaces, projects, the
  model allowlist, and API keys (create returns the raw key once; revoke).
- **RBAC** — resolve a *principal* from either the superuser admin token or a
  **user session token**; enforce `owner > admin > member` per organization on
  every management call.
- **Sessions** — `POST /manage/sessions` issues a bearer session token for a
  user (POC: no password; represents "logged in").
- **Activity log** — security events (org/member/key/budget changes) recorded to
  an `activity_logs` table and listable per org.
- **Alembic migrations** — replace startup `create_all` as the prod schema path
  (async `env.py` + an initial autogenerated revision). `create_all` stays for
  tests/dev convenience.

**Steps (TDD)**
1. Models: `sessions`, `activity_logs` (+ role helpers). Test role ordering.
2. `rbac.py`: principal resolution + `require_role(org, min_role)`. Test 403s.
3. `manage.py`: CRUD endpoints, each guarded + writing an activity entry.
4. Alembic scaffold; verify `uv run alembic upgrade head` on a clean DB.

---

## 12. Phase 4 — Scale, resilience & developer experience

**Scope**
- **Spend budgets** — optional monthly credit cap per workspace; the guard sums
  month-to-date spend and returns `402` when the cap is hit (separate from a
  zero balance).
- **Upstream retries** — retry transient upstream failures (connect/timeout/5xx)
  with capped exponential backoff.
- **Cross-provider translation** — let an OpenAI-format client call an Anthropic
  model: translate request → Anthropic Messages, call upstream, translate the
  response back to an OpenAI `chat.completion`. Config-gated.
- **Observability** — in-process counters exposed at `GET /metrics` in
  Prometheus text format (requests, tokens, errors by model/status).
- **Deploy** — `Dockerfile`, `docker-compose.yml` (gateway + Postgres + Redis),
  and a `Makefile`.

**Steps (TDD)**
1. `budgets.py` + `monthly_budget_micros`; guard integration. Test over/under cap.
2. Retry wrapper in `upstream.py`. Test fail-once-then-succeed.
3. `translate.py` (OpenAI↔Anthropic). Test with respx.
4. `metrics.py` + `/metrics`. Test counter increments.
5. Docker/compose/Makefile (deploy artifacts; not unit-tested).

---

## 13. Phase 5 — Wiring the remaining backends (done)

The two pieces earlier left as config-only scaffolding are now fully wired,
each with a graceful fallback so the gateway still runs with zero external
services.

**Redis-backed rate limiting** (`ratelimit.py`)
- Pluggable async limiter: in-memory token bucket (default) **or** a Redis
  fixed-window counter when `REDIS_URL` is set. Selected at startup via
  `build_from_settings()`. Tested with `fakeredis` (unit + through the gateway).

**Stripe Checkout + webhooks** (`payments.py`)
- `POST /admin/workspaces/{id}/checkout` creates a real Stripe Checkout Session
  (via the REST API over httpx — no SDK dep) and returns its URL; the payment is
  recorded `pending` with the session id.
- `POST /admin/webhooks/stripe` verifies the `Stripe-Signature` HMAC and, on
  `checkout.session.completed`, settles the payment and applies credits
  (idempotent). Mock mode (no key) still settles top-ups immediately.
- Tested with respx (Checkout API) + a locally signed webhook payload.

---

## Summary

Phase 1 is a **single FastAPI service (Python + uv) + Postgres**, built
**test-first (TDD)**, that proxies OpenAI/Anthropic/Gemini via pass-through,
authenticates hashed `atp-…` keys, meters tokens from upstream usage, and debits
an integer credit ledger inside one transaction per request. A **single Vue 3
(CDN) `index.html`** provides a read-only console for balance, keys, and usage.
Build it in ten red→green→refactor steps, starting from a hardcoded bare proxy
and layering auth → billing → allowlist → streaming → multi-provider → console.
Payments, rate limiting, and a full SPA come in Phase 2.
