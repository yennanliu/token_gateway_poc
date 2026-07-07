# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A multi-provider **LLM API gateway** (OpenAI / Anthropic / Gemini compatible). Clients point any provider SDK at this gateway by changing only the **base URL** and **API key** (`gw-…`) — no wrapper library. The gateway authenticates the key, enforces a per-project model allowlist, rate limits, checks the workspace credit balance and monthly budget, forwards the request to the real provider (injecting the real upstream key), meters token usage, and debits credits.

Python 3.12 · uv · FastAPI · httpx · SQLAlchemy 2 (async) · SQLite (default) / Postgres · Redis (optional) · Vue 3 CDN console. Built test-first with pytest + respx.

## Commands

```bash
make install        # uv sync --extra dev
make test           # uv run pytest -q  (all 91 tests)
make run            # uv run uvicorn gateway.main:app --reload  (console at http://localhost:8000/)
make migrate        # uv run alembic upgrade head
make revision m="…" # autogenerate a migration
make up / make down # docker compose (gateway + Postgres + Redis)

uv run pytest -q -m unit                    # 41 fast pure-logic tests (tests/unit/*)
uv run pytest -q -m integration             # 50 full-stack tests (ASGI app + DB + mocked upstream)
uv run pytest -q tests/test_billing.py      # single file
uv run pytest -q tests/test_billing.py::test_name   # single test
```

Tests are auto-tagged **by location** (see `pytest_collection_modifyitems` in `tests/conftest.py`): `tests/unit/*` → `unit`, everything else → `integration`. There is no lint/format step wired into the Makefile.

## Architecture

Request flow for a proxied call: **router → `auth.guard` → `upstream.forward_*` → `billing.record_usage_and_debit` + `logs.record_request`**.

- **Routers** (`src/gateway/routers/{openai,anthropic,gemini,models}.py`) are thin. Each parses the body, extracts the model, sets a `style` string (`"openai"|"anthropic"|"gemini"`), and delegates to `proxy.handle(...)`. The `style` threads through everything so errors are rendered in the shape the *calling* SDK expects (`errors.render_error`).
- **`proxy.py`** is the shared engine. Non-streaming: forward → read upstream `usage` → settle. Streaming: tee bytes to the client via `StreamingResponse` while collecting them, then parse usage out of the SSE stream and bill in a **fresh DB session** in the `finally` block (the request-scoped session is gone by the time the stream closes — this is deliberate). Usage extractors are passed in as callables (`usage.from_openai`, `proxy.openai_stream_usage`, etc.).
- **`upstream.py`** holds per-provider `Upstream` adapters (URL + real-key injection) and a single shared `httpx.AsyncClient`. `forward_json` retries transient failures (connect/timeout/502/503/504) with capped exponential backoff.
- **`auth.guard`** is the single pre-flight gate, in order: authenticate key → rate limit → credit balance > 0 → within monthly budget → model in project allowlist. Any failure raises a `GatewayError`.

### Data model (`models.py`)

Hierarchy: `Organization → Workspace → Project → ApiKey`. Credits live on the **Workspace** (`credit_micros`); the model allowlist is the *presence* of `ProjectModel` rows for a project. Keys are `gw-<62 base62>`; only the SHA-256 hash + short display prefix are stored (`keys.py`). Sessions/RBAC use `sess-…` tokens (hashed).

**Money is integer micros throughout: 1_000_000 micros = 1 credit = $0.01.** Never use floats for money. Pricing (`pricing.py`) is micros-per-token per model, with a non-zero `DEFAULT_RATE` fallback so unknown models never bill zero. All balance changes go through `billing.py` as one atomic transaction (UsageEvent + negative LedgerEntry + workspace decrement).

### Auth surfaces (three distinct token types)

- **`gw-…` API keys** — for proxy traffic; resolved by `auth.py`. Accepted via `Authorization: Bearer`, `x-api-key`, `x-goog-api-key`, or `?key=`.
- **`X-Admin-Token`** — superuser token (`settings.admin_token`) for the console (`/admin/*`) and as an RBAC bypass.
- **`sess-…` session tokens** — user sessions for the control plane (`/manage/*`), gated by `rbac.require_role` with `owner > admin > member` per organization.

### Pluggable backends

- **Rate limiter** (`ratelimit.py`): in-memory token bucket by default; Redis fixed-window when `REDIS_URL` is set. Selected at startup by `build_from_settings()`. Both implement `async allow(key_id, rpm)`; `rpm=0` = unlimited.
- **Payments** (`payments.py`): mock mode (top-ups apply credits immediately) unless `STRIPE_SECRET_KEY` is set, then real Checkout + signed webhooks.
- **Translation** (`translate.py`): when `ENABLE_TRANSLATION=true`, an OpenAI-format request for a `claude-*` model is translated to the Anthropic Messages format and the response translated back.

### DB lifecycle

Dev/test **auto-creates** tables via `db.create_all()` in the app lifespan (and in test fixtures). **Production uses Alembic** (`make migrate`) — when you change `models.py`, generate a migration. Column types are kept portable so the same models run on both SQLite and Postgres. Tests inject an in-memory SQLite engine via `db.configure_engine` (`StaticPool` so all sessions share one connection).

## Testing conventions

`tests/conftest.py` sets fake upstream keys in `os.environ` **before** settings are first read, then clears the `get_settings` LRU cache. respx does **not** intercept `ASGITransport`, so respx mocks only the gateway's *outbound upstream* HTTP calls, not calls into the app. Use the `seed` fixture for a ready workspace+project+key (returns the raw key). Prefer adding pure-logic tests under `tests/unit/` (they get the `unit` marker automatically and run without app/DB/network).

## Docs

Design and rationale live in `doc/` — start with `doc/design-and-implementation.md`. The README documents the phase map (Phases 1–5) describing how features were layered in.
