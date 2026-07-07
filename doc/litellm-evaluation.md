# Should we rebuild on LiteLLM? — An evaluation

**Date:** 2026-07-07
**Question:** Refactor this gateway to be built *on top of* [LiteLLM](https://www.litellm.ai/), then layer our own features (token/credit, monitoring, rate limiting, multi-tenancy) and deploy to AWS — or keep the current custom approach?

**Verdict (short version):** **Keep the current control/billing plane as the system of record. Do *not* do a wholesale refactor onto LiteLLM.** Adopt LiteLLM selectively — as an optional *upstream forwarding library* — only when provider breadth (beyond OpenAI/Anthropic/Gemini) or routing/fallback/caching becomes a real product requirement. The one thing that makes this product a product — a **prepaid, integer-precision, atomically-debited credit ledger** — is precisely the thing LiteLLM does *not* do (it is postpaid, float-based, soft-limit). Rebuilding on LiteLLM would mean fighting its core model to re-create what we already have.

---

## 1. What we already have

A well-structured, test-first gateway (`src/gateway/`, ~2,527 LOC, 91 passing tests, CI with migration-drift guard, Docker + Alembic). It already implements almost the entire list of "other features" the proposal wants to build on top of LiteLLM:

| Capability | Status today | Where |
|---|---|---|
| Multi-provider proxy (OpenAI / Anthropic / Gemini, native-shaped endpoints) | Mature | `routers/*`, `upstream.py`, `proxy.py` |
| Streaming (SSE tee, bills even on client disconnect) | Mature | `proxy.py` |
| **Token metering + prepaid credit ledger (integer micros, atomic debit)** | **Mature** | `billing.py`, `usage.py`, `pricing.py` |
| Rate limiting (in-mem bucket / Redis fixed-window, per-key RPM) | Done | `ratelimit.py` |
| Multi-tenancy Org → Workspace → Project → Key | Done | `models.py`, `manage.py` |
| Monthly budgets (per-workspace MTD enforcement) | Done | `budgets.py` |
| RBAC (owner/admin/member, sessions, superuser token) | Done | `rbac.py`, `manage.py` |
| Payments (mock + real Stripe Checkout + signed webhook) | Done | `payments.py` |
| Request logging / usage events / audit log | Done | `logs.py`, `activity.py` |
| Monitoring (Prometheus `/metrics`) | Done (in-process) | `metrics.py` |
| Admin console (Vue 3 CDN) | Minimal | `frontend/index.html` |
| Format translation (OpenAI↔Anthropic) | Partial | `translate.py` |

**Read that table against the proposal.** The proposal is "build on LiteLLM, then develop token/monitor/rate-limit/multi-tenancy." Those features are *already built here*, and tuned to a prepaid credit model. LiteLLM would not save us that work — it would ask us to redo it in its idiom.

---

## 2. What LiteLLM actually is

LiteLLM (BerriAI, MIT-licensed core) is two things:
- a **Python SDK** that normalizes 100+ providers to the OpenAI format, and
- a **Proxy Server ("AI Gateway")** — a Postgres-backed FastAPI service offering virtual keys, spend tracking, budgets, rate limits, routing/fallbacks/load-balancing, caching, guardrails, and logging callbacks.

Its genuine strengths, which we do **not** have:
- **Provider breadth** — 100+ providers (Bedrock, Vertex, Azure, Cohere, vLLM, NIM, …) vs our 3. This is the single biggest reason to care about LiteLLM.
- **Routing** — load-balancing across deployments, automatic fallbacks, cooldowns, retries across providers. We have per-provider retry only.
- **Caching** — semantic/response caching. We have none.
- **Battle-tested breadth + community** — large user base, frequent releases.

Sources: [Getting Started](https://docs.litellm.ai/docs/), [AI Gateway](https://docs.litellm.ai/docs/simple_proxy), [GitHub](https://github.com/BerriAI/litellm).

---

## 3. The decisive mismatch: billing model

This is the crux, so it gets its own section.

| Dimension | **Our gateway** | **LiteLLM** |
|---|---|---|
| Accounting model | **Prepaid** — buy credits, then spend | **Postpaid** — spend accrues, tracked after the fact |
| Money precision | **Integer micros** (1e6 micros = 1 credit = $0.01); never floats | **Floating-point dollars** (e.g. `"spend": 0.000002`) |
| Enforcement | **Hard** — balance checked pre-flight, atomic debit (UsageEvent + negative LedgerEntry + workspace decrement) in one transaction; balance can't go negative | **Soft** — `max_budget` limits with cooldowns; enforcement is best-effort, not a prepaid balance gate |
| System of record | A ledger (`ledger_entries`, `payments`) you can audit and reconcile to the cent | Spend logs (`LiteLLMSpendLogs`), aggregated for reporting |

Source: [LiteLLM cost tracking](https://docs.litellm.ai/docs/proxy/cost_tracking).

If the product is a **prepaid token/credit gateway** (which the schema, the `_micros` discipline, the atomic-debit path, and the Stripe top-up flow all say it is), then LiteLLM's model is the wrong shape. Float money invites rounding drift in a ledger; soft budgets can't guarantee "no credit, no call." We would end up bolting our own prepaid ledger *back on top of* LiteLLM — running two spend systems that must be reconciled — which is strictly worse than owning one.

---

## 4. The other mismatch: tenancy hierarchy is partly paywalled

Our hierarchy is **Org → Workspace → Project → Key** (4 levels), with credits/budgets at the Workspace.

LiteLLM's hierarchy is **Organization → Team → User → Key** (4 levels) — but **Organizations are an Enterprise (paid) feature**. Only **Team → User → Key** are open-source. So on the free tier we'd map:

- Workspace → Team (OK, budgets/limits live here — good fit)
- Project → ??? (no clean layer; Teams are the budget boundary, not Projects)
- Org → Enterprise-only

Our Project layer (which owns the model allowlist and API keys) has no free-tier equivalent, and our Org layer requires the Enterprise license. Enterprise runs ~$250/mo (Basic) up to ~$30k/yr (Premium); SSO is free only up to 5 users; audit logs and several guardrails are Enterprise-gated.

Sources: [Multi-tenant architecture](https://docs.litellm.ai/docs/proxy/multi_tenant_architecture), [Enterprise](https://docs.litellm.ai/docs/enterprise), [pricing overview](https://www.truefoundry.com/blog/litellm-pricing-guide).

---

## 5. Three options, weighed

### Option A — Full refactor: rebuild on the LiteLLM Proxy
Replace our proxy/billing/tenancy with LiteLLM's, keep only a thin custom layer.

- ✅ Instant 100+ providers, routing, fallbacks, caching.
- ❌ Rebuild prepaid credit ledger *against the grain* of a postpaid float system — the hardest, most valuable part of our code, redone worse.
- ❌ Our Project layer and Org layer don't fit the free tier; Org needs Enterprise.
- ❌ Throw away ~2,500 LOC of tested, working, purpose-fit code and its 91-test safety net.
- ❌ Adopt a large, fast-moving dependency and its opinionated schema as our core.
- **Effort:** high (weeks); **Risk:** high; **Payoff:** provider breadth we don't yet need.

### Option B — Keep current; ignore LiteLLM
- ✅ Zero migration risk; billing/tenancy stay exactly right.
- ✅ Clean, small, fully-owned, fully-tested.
- ❌ Stuck at 3 providers; no routing/fallback/caching unless we build them.
- **Effort:** none; **Risk:** none; **Payoff:** — .

### Option C — **Recommended: keep our plane; use LiteLLM as an optional forwarding library**
Keep our control/billing/tenancy plane as the system of record. Where provider breadth or routing matters, swap the hand-rolled `upstream.py` adapters for a call into the **LiteLLM SDK** (or a co-located LiteLLM proxy) as a pure forwarding engine. Our pre-flight `guard()` (auth → rate limit → credit → budget → allowlist) and our atomic debit remain unchanged; LiteLLM just becomes "the thing that talks to 100 providers and returns usage."

- ✅ Get provider breadth + routing/fallback/caching **only where we opt in**.
- ✅ Prepaid ledger, integer micros, hard enforcement, our exact tenancy — untouched.
- ✅ Incremental and reversible: it slots in behind the existing `Upstream` abstraction.
- ⚠️ Adds a heavyweight dependency; we only own the seam (usage-shape mapping, error mapping).
- **Effort:** low–medium and staged; **Risk:** contained; **Payoff:** the parts of LiteLLM that are actually hard to build ourselves.

`upstream.py` already isolates "how we reach a provider" behind an adapter with a shared client and retry — that is exactly the seam where a LiteLLM backend drops in, one provider at a time, without disturbing billing.

---

## 6. AWS deployment (independent of the LiteLLM decision)

Our Docker image + Postgres + Redis maps to AWS cleanly today, no LiteLLM required:

- **Compute:** ECS Fargate (simplest) or EKS. Our container already runs `alembic upgrade head` then uvicorn.
- **DB:** RDS for PostgreSQL (we already support Postgres via `asyncpg`; migrations exist).
- **Cache/limiter:** ElastiCache for Redis → enables the multi-instance rate limiter (`ratelimit.py` already switches on `REDIS_URL`).
- **Secrets:** Secrets Manager / SSM for provider keys, admin token, Stripe keys (today via env).
- **Ingress:** ALB (must allow SSE / streaming responses — disable response buffering).
- **Before prod, address the known gaps** (already noted in `doc/follow-ups.md`): metrics are in-process (move to a shared store or scrape per-instance + aggregate), `/admin/*` uses a single static token (add per-user auth), pricing is an illustrative table (wire real rate cards), and consider request-body logging policy.

The same AWS shape hosts Option C: run a LiteLLM proxy as a **sidecar/second service** in the same cluster, private to our gateway, if/when we adopt it.

---

## 7. Recommendation

1. **Do not rebuild on LiteLLM.** Our differentiator is a prepaid, precise, hard-enforced credit ledger and a bespoke tenancy model — the exact things LiteLLM inverts (postpaid, float, soft) or paywalls (Org layer). A full refactor trades working, purpose-fit code for a mismatch.
2. **Keep the current control/billing plane** and ship it to AWS on the path in §6 after closing the `follow-ups.md` gaps.
3. **Adopt LiteLLM as Option C — an optional forwarding backend behind `upstream.py`** — the moment "we need provider N" or "we need cross-provider fallback/caching" becomes a real requirement. Prototype it for one provider first; measure the seam cost before committing.
4. **Revisit a deeper LiteLLM dependency only if** provider breadth becomes the dominant requirement *and* the product model shifts from prepaid credits to postpaid billing. Until then, LiteLLM is a component, not a foundation.

### One-line decision aid
> If the question is *"who owns the money and the tenants?"* the answer must stay **us**. If the question is *"who talks to the 100th provider?"* the answer can be **LiteLLM**.
