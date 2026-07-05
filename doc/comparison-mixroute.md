# Comparison: MixRoute vs. this project — and ideas

> Internal analysis. Reference: <https://mixroute.ai/zh-hant/>
> Compiled: 2026-07-05

Comparing the hosted gateway **MixRoute** against our `token_gateway_poc`, and a
prioritized list of ideas to adopt.

---

## What MixRoute is

A hosted "one key, all vendors" gateway: **200+ models across 20+ providers**
(OpenAI, Anthropic, Google, Mistral, Meta, Cohere, DeepSeek, xAI, Bedrock,
Azure…), OpenAI-SDK-compatible, with **reserved capacity + millisecond automatic
failover**, **zero-markup** pay-as-you-go billing (single unified bill, no card
binding), a **zero-storage** privacy stance (prompts only in memory, never
logged), and a real-time cost dashboard.

---

## Head-to-head

| Dimension | MixRoute | This project |
|---|---|---|
| **Providers / models** | 200+ models, 20+ providers | 3 providers (OpenAI, Anthropic, Gemini), static per-project allowlist |
| **API compatibility** | OpenAI SDK only (base_url swap) | OpenAI **+ Anthropic + Gemini native** formats, **+ OpenAI→Anthropic translation** ← broader |
| **Routing / failover** | Auto failover (ms), reserved capacity, global scheduling, multi-key | Same-endpoint **retries w/ backoff** only — no provider fallback, no key rotation, no LB |
| **Billing model** | Zero-markup, pay-as-you-go, no card | Prepaid **credit ledger** + configurable per-model rates + monthly **budgets** + Stripe top-ups |
| **Privacy** | "Zero-storage", only metadata | Also **never stores prompt/response bodies** (only tokens/status/latency) — but undocumented |
| **Multi-tenancy / RBAC** | Enterprise tiers (light detail) | Full **org→workspace→project→key** + owner/admin/member RBAC + activity log ← stronger |
| **Dashboard / metrics** | Real-time cost dashboard | Vue console + `/metrics` (Prometheus) + analytics/logs |
| **Deploy** | Hosted SaaS | **Self-hostable** (Docker/compose, Postgres/Redis), migrations, 91 tests + CI |

**Net read:** MixRoute wins on *breadth* (models/providers), *reliability infra*
(failover, reserved capacity, key rotation), and *positioning* (zero-markup,
privacy guarantee). We win on *protocol depth* (3 native SDKs, not just OpenAI),
*multi-tenant control plane / RBAC*, *budgets*, and being *open, self-hostable,
and tested*.

---

## Ideas (prioritized, mapped to our code)

### High impact, low effort
1. **Model → provider registry (dynamic routing).** Provider choice is currently
   hard-coded per route. Introduce a `model_catalog` (config/DB) mapping
   `model_id → {provider, upstream_model, rates}`. This is the unlock for adding
   DeepSeek/xAI/Mistral without new routes — turns 3 providers into N. Touches
   `upstream.py`, `pricing.py`, `routers/`.
2. **Multi-key rotation per provider.** Accept a pool of upstream keys
   (`OPENAI_API_KEYS=k1,k2,…`); round-robin and retry the *next* key on
   `429/401`. Small change in `upstream.py`, big reliability win.
3. **Document + guarantee the zero-storage privacy stance.** We already don't
   persist prompt/response bodies — make it an explicit, tested guarantee (a test
   asserting `RequestLog`/`UsageEvent` never contain body text) plus a
   README/console line. Cheap credibility.
4. **Configurable markup/margin.** Add a `markup_multiplier` to pricing so
   operators can pick zero-markup *or* a margin. Rate table already exists.

### High impact, medium effort
5. **Cross-provider fallback chains.** Extend retries into fallback: if provider A
   fails/over-quota, retry an equivalent model at provider B (e.g.
   `gpt-5.4 → claude-sonnet-4-6`). Needs the registry (#1) + our translation layer.
6. **Model aliases / virtual models.** e.g. `"auto"`, `"cheapest"`,
   `"fastest-coding"` resolve to a concrete model by policy (cost/latency). Sits
   on top of #1.
7. **Richer analytics.** Add p50/p95 **latency** and cost-over-time to the
   dashboard — we already capture `latency_ms` in `RequestLog`, it's just not
   surfaced.
8. **Provider health checks + circuit breaker.** Background pings per provider,
   shown in the console and used to skip unhealthy upstreams.

### Nice to have
9. **Response caching** for identical (model + messages) requests — opt-in,
   TTL'd, Redis-backed (Redis already wired).
10. **Broaden native SDK compatibility** as providers are added (already a
    strength).
11. **Reserved capacity / provisioned throughput** — infra-heavy SaaS territory;
    likely out of scope for a self-hosted POC, noted as the enterprise
    differentiator we don't need to match.

---

## Suggested build order

Start with **#1 (model registry)** and **#2 (multi-key rotation)** — everything
else (fallback chains, aliases, more providers) builds on the registry, and key
rotation is the cheapest reliability gain. Then #3/#4 (privacy doc + markup) as
quick wins, then #5/#7 for the biggest visible value.
