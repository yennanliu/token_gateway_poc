# How to Build a Token Gateway

> Companion to [`reference-gateway.md`](./reference-gateway.md).
> A blueprint for building your own multi-provider LLM gateway.
> Compiled: 2026-07-05

This document describes how to build a system with this core idea:
a **single OpenAI/Anthropic/Gemini-compatible API endpoint**, backed
by **one API key** and **one shared pool of pay-as-you-go credits**, that proxies
requests to multiple upstream LLM providers while metering usage and billing.

---

## 1. The core idea in one sentence

> Sit a **reverse proxy** in front of OpenAI, Anthropic, and Google Gemini that
> (a) accepts each provider's *native* SDK wire format, (b) authenticates with
> **your own** `xxx-…` key, (c) meters token usage, (d) debits credits, and
> (e) forwards the request upstream with the *real* provider key.

Everything else — console, billing, analytics — is built around that proxy.

---

## 2. Why it works: the compatibility trick

Provider SDKs are configurable in exactly two places you need:

1. **Base URL** — every official SDK lets you override the host.
2. **API key** — a plain string the SDK puts into a header.

So if your gateway *speaks the same wire protocol* as the provider on a given
path, the SDK cannot tell the difference. You expose:

| Path | Wire format to emulate | Header the SDK sends |
|------|------------------------|----------------------|
| `POST /v1/chat/completions` | OpenAI Chat Completions | `Authorization: Bearer <key>` |
| `POST /v1/messages` | Anthropic Messages | `Authorization: Bearer <key>` (or `x-api-key`) |
| `POST /v1/models/{model}:generateContent` | Gemini generateContent | `x-goog-api-key: <key>` |
| `GET /v1/models` | OpenAI model list | `Authorization: Bearer <key>` |

Accept the key in **all** locations (`Authorization: Bearer`, `x-api-key`,
`x-goog-api-key`, `?key=`) so any SDK's default just works.

---

## 3. High-level architecture

```
                 ┌─────────────────────────────────────────────┐
   client SDK    │                 GATEWAY                      │
  (OpenAI/       │                                             │
   Anthropic/ ──►│  [1] Edge / TLS                             │
   Gemini/CLI)   │       │                                     │
                 │  [2] Auth middleware  ──► key store         │
                 │       │                                     │
                 │  [3] Rate limit / quota                     │
                 │       │                                     │
                 │  [4] Router (path → provider adapter)       │
                 │       │                                     │
                 │  [5] Provider adapter ──► upstream provider │──► OpenAI
                 │       │  (inject real key, translate)       │──► Anthropic
                 │       │                                     │──► Gemini
                 │  [6] Usage meter (tokens in/out)            │
                 │       │                                     │
                 │  [7] Billing ledger (debit credits)         │──► DB
                 │       │                                     │
                 │  [8] Logging / analytics                    │──► DB / warehouse
                 └─────────────────────────────────────────────┘
```

The response path runs the same stages in reverse: stream/forward bytes back,
count output tokens, then write the usage + ledger entry.

---

## 4. Data model

Mirror the reference gateway's four-level hierarchy:

```
Organization (1) ─── (N) Workspace (holds credit balance)
                              │
                              └── (N) Project (model allowlist + optional balance)
                                        │
                                        └── (N) ApiKey (hashed, scoped to project)
```

Suggested tables:

```sql
organizations(id, name, owner_user_id, created_at)
users(id, email, ...)
memberships(user_id, org_id | workspace_id | project_id, role)  -- owner/admin/member

workspaces(id, org_id, name, credit_balance_micros)
projects(id, workspace_id, name, credit_balance_micros NULL)
project_models(project_id, model_id, enabled)                    -- the allowlist

api_keys(
  id, project_id,
  key_prefix,          -- e.g. 'gw-' + first 8 chars, for display
  key_hash,            -- store a hash, NEVER the raw key
  scopes, revoked_at, last_used_at, created_at
)

-- usage & billing
usage_events(
  id, api_key_id, project_id, model_id,
  input_tokens, output_tokens,
  cost_micros,         -- computed at request time
  status, latency_ms, created_at
)
ledger_entries(id, workspace_id, delta_micros, reason, ref_id, created_at)
top_ups(id, workspace_id, amount_usd, credits, payment_ref, created_at)
```

Use integer **micro-credits** (or micro-USD) everywhere; never floats for money.

---

## 5. Building each stage

### [1] Edge / TLS
Any reverse proxy (nginx, Caddy, cloud LB) terminating TLS in front of your app.
Nothing gateway-specific here.

### [2] Authentication
- Generate keys as `prefix-` + 32+ bytes of CSPRNG randomness, base62-encoded
  (the reference gateway uses `gw-…`, 92 chars total).
- Store only a **hash** (SHA-256 or Argon2) + a display prefix. On each request:
  read the key from any accepted header/query, hash it, look it up, check
  `revoked_at`.
- Resolve the key → project → workspace so later stages have the billing context.

### [3] Rate limiting & quota
- Per-key and per-project rate limits (token bucket in Redis).
- Reject with `429` when over rate; `402` when credit balance ≤ 0.

### [4] Router
Match the request path to a **provider adapter**. The path *is* the protocol
declaration:
- `/v1/chat/completions`, `/v1/models` → OpenAI-style
- `/v1/messages` → Anthropic-style
- `/v1/models/{m}:generateContent` → Gemini-style

Also validate the requested `model` against `project_models` → return `403`
("model not enabled for project") if not allowed. Remember: **listing a model
via `/v1/models` is a menu, not a grant.**

### [5] Provider adapter
Each adapter knows how to talk to one upstream. Two designs:

- **Pass-through (simplest):** if the client used the OpenAI format and you're
  routing to OpenAI, just swap the key and forward the body verbatim.
- **Translating:** if you want *any* client format to reach *any* provider,
  translate request → canonical → provider, and provider response → client
  format. (Optional; start with pass-through per-provider.)

The adapter:
1. Removes the client's `gw-…` key.
2. Injects the **real upstream key** (from your secrets manager).
3. Rewrites the base URL to the provider's host.
4. Forwards, streaming if requested.

### [6] Usage metering
- **Input tokens:** count from the request (tokenizer per model family) or trust
  the provider's `usage` in the response.
- **Output tokens:** from the provider `usage` field, or count streamed deltas.
- For streaming, accumulate as chunks arrive; finalize on `data: [DONE]`
  (OpenAI) / `message_stop` (Anthropic).

### [7] Billing ledger
- Price = `(input_tokens * in_rate) + (output_tokens * out_rate)` per model.
- Convert to micro-credits (reference: **1 credit = $0.01**).
- Write a `usage_event` + a negative `ledger_entry`, decrement
  `workspaces.credit_balance_micros` **atomically** (single transaction).
- Top-ups add positive ledger entries. Credits are **non-expiring**.

### [8] Logging & analytics
- Persist every request: key, model, status, tokens, latency.
- Power the console: usage by model/key, filterable request logs, and a
  security **activity log** (sign-ins, invites, key creation, quota changes).

---

## 6. Streaming (don't buffer)

Streaming is where naive proxies break. Stream bytes through end-to-end:

- **OpenAI:** proxy SSE lines unchanged; watch for `data: [DONE]`.
- **Anthropic:** forward the event sequence `message_start` →
  `content_block_delta` → … → `message_stop`.

Use a streaming HTTP client and an async/streaming response on your side
(e.g. `StreamingResponse` in FastAPI, or Node streams). Meter tokens *as they
flow*; write the ledger entry when the stream closes (including on client
disconnect — bill for what was generated).

---

## 7. Error contract

Adopt the reference gateway's status codes so SDKs behave predictably:

| HTTP | When you return it |
|------|--------------------|
| `400` | Malformed body / unknown params |
| `401` | Key missing, unknown, or revoked |
| `402` | Insufficient credits |
| `403` | Model not enabled for this project |
| `429` | Rate limited |
| `502` / `503` | Upstream provider error / unavailable |

Return errors in the **shape the client SDK expects** (OpenAI error envelope on
`/v1/chat/completions`, Anthropic error on `/v1/messages`) so SDK error handling
still works.

---

## 8. The console (web app)

A separate front-end + API for humans:
- Sign up → create org/workspace/project.
- Create & revoke API keys (show the raw key **once**).
- Manage the per-project model allowlist.
- Buy credits (Stripe or similar) → top-up writes ledger entries.
- Dashboards: usage analytics, request logs, activity log, team roles
  (Owner / Admin / Member).

---

## 9. Suggested tech stack

| Concern | Reasonable choice |
|---------|-------------------|
| Gateway service | Go, Rust, or Python (FastAPI) / Node — needs good streaming |
| Data store | Postgres (ledger, keys, usage) |
| Rate limit / cache | Redis |
| Secrets (upstream keys) | Vault / cloud secrets manager (never in DB plaintext) |
| Payments | Stripe |
| Analytics | Postgres + a warehouse (BigQuery/ClickHouse) for heavy query |
| Console | Next.js / React |

---

## 10. Minimal MVP path

Build in this order — each step is independently testable:

1. **Bare proxy:** `POST /v1/chat/completions` → forward to OpenAI with a
   hardcoded key. Confirm the OpenAI SDK works by only changing `base_url`.
2. **Key auth:** issue `xxx-…` keys, hash-store them, authenticate requests.
3. **Metering + ledger:** count tokens, price them, debit a credit balance;
   return `402` at zero.
4. **Multi-provider:** add Anthropic `/v1/messages` and Gemini
   `:generateContent` adapters.
5. **Streaming:** stream all three end-to-end.
6. **Model allowlist:** per-project enablement + `403`.
7. **Console + top-ups:** keys, dashboards, Stripe.

At step 1 you already have something useful; steps 2–3 make it a *gateway*;
steps 4–7 make it a *product*.

---

## 11. Things to get right early

- **Money is integers.** Micro-credits, atomic transactions, no floats.
- **Never store raw keys** — hash + prefix only.
- **Stream, don't buffer** — or you'll break long responses and TTFT.
- **Bill on partial output** — meter on stream close, even on disconnect.
- **Isolate upstream keys** — a client key must never leak the real provider key.
- **Model menu ≠ grant** — discovery lists availability; the project allowlist
  controls access.

---

## Summary

Building this kind of gateway is fundamentally: a **protocol-faithful
reverse proxy** (so provider SDKs work by changing only base URL + key), wrapped
with **auth, per-project model allowlists, token metering, a credit ledger, and a
console**. Start with a one-provider pass-through proxy, add key auth and a
metered credit ledger, then fan out to all three providers with streaming — and
you have the same thing.
