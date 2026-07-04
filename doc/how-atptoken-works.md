# How atptoken.ai Works

> Source: <https://atptoken.ai/docs/>
> Compiled: 2026-07-05

This document explains what the **ATP Token** site/product is and how it works,
based on its public documentation.

---

## 1. What it is

**ATP Token** is a **unified LLM API gateway**. It sits in front of multiple
model providers — **OpenAI, Anthropic, and Google Gemini** — and exposes them
through a single, standardized, provider-compatible interface.

The core promise: **you keep using each provider's own SDK unchanged.** You only
swap the *base URL* and the *API key*. No wrapper library is needed.

> "The Gateway accepts the OpenAI, Anthropic, and Google GenAI SDKs using each
> SDK's default authentication header — no wrapper library needed."

One ATP key + one balance of credits gives you access to models across all three
providers.

---

## 2. Account model (four-level hierarchy)

Resources are organized as a nested hierarchy. Each level has a distinct job:

| Level | Role |
|-------|------|
| **Organization** | Billing and team boundary (the top-level tenant) |
| **Workspace** | Credit container — holds the credit balance |
| **Project** | Model allowlist + credit balance; defines *which* models are usable |
| **API Key** | Scoped credential (`atp-…`, 92 chars) tied to a project |

Key idea: **the model list is the menu, not your key's permissions.** Being able
to *see* a model via discovery doesn't mean your key/project is allowed to *use*
it — access is enabled per project.

---

## 3. Authentication

Keys use the format `atp-…` (92 characters total). The gateway accepts the key
in three locations so that each provider SDK works with its native header:

| Location | Header / form | Used by |
|----------|---------------|---------|
| Bearer token | `Authorization: Bearer atp-…` | OpenAI SDK, Anthropic SDK, curl |
| Google header | `x-goog-api-key: atp-…` | Google GenAI SDK |
| Query parameter | `?key=atp-…` | REST clients |

---

## 4. Base URLs

Different SDKs expect the version path in different places:

- **OpenAI SDK / Codex:** `https://api.atptoken.ai/v1`
- **Anthropic SDK / Claude Code:** `https://api.atptoken.ai`
- **Google GenAI SDK:** `https://api.atptoken.ai`

---

## 5. Using it from each SDK

### OpenAI (Python)
```python
from openai import OpenAI
client = OpenAI(
    base_url="https://api.atptoken.ai/v1",
    api_key="atp-..."
)
```

### Anthropic (Python)
```python
from anthropic import Anthropic
client = Anthropic(
    base_url="https://api.atptoken.ai",
    api_key="atp-..."
)
```

### Google GenAI (Python)
```python
from google import genai
client = genai.Client(
    api_key="atp-...",
    http_options={"base_url": "https://api.atptoken.ai"}
)
```

### curl
```bash
# List models
curl https://api.atptoken.ai/v1/models \
  -H "Authorization: Bearer atp-..."

# OpenAI-compatible chat
curl https://api.atptoken.ai/v1/chat/completions \
  -H "Authorization: Bearer atp-..." \
  -H "Content-Type: application/json" \
  -d '{"model":"<model>","messages":[{"role":"user","content":"hi"}]}'

# Anthropic-compatible messages
curl https://api.atptoken.ai/v1/messages \
  -H "Authorization: Bearer atp-..." \
  -H "Content-Type: application/json" \
  -d '{"model":"<model>","max_tokens":256,"messages":[{"role":"user","content":"hi"}]}'

# Gemini-compatible generate
curl "https://api.atptoken.ai/v1/models/<model>:generateContent" \
  -H "x-goog-api-key: atp-..." \
  -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"hi"}]}]}'

# File upload
curl https://api.atptoken.ai/v1/files \
  -H "Authorization: Bearer atp-..." \
  -F "file=@./input.pdf"
```

---

## 6. API endpoints

| Endpoint | Purpose | Compatible with |
|----------|---------|-----------------|
| `GET /v1/models` | List available models (dynamic discovery) | OpenAI |
| `POST /v1/chat/completions` | Chat requests | OpenAI |
| `POST /v1/messages` | Message API | Anthropic |
| `POST /v1/models/{model}:generateContent` | Content generation | Gemini |
| `POST /v1/files` | File upload (max 20 MB) | — |

### Example responses

**Model list** (`GET /v1/models`):
```json
{
  "object": "list",
  "data": [
    {"id":"claude-sonnet-4-6","object":"model","created":1700000000,"owned_by":"llm-gateway"},
    {"id":"gpt-5.4","object":"model","created":1700000000,"owned_by":"llm-gateway"}
  ]
}
```

**Chat completion**:
```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "<model>",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "..."},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21}
}
```

**File upload**:
```json
{"gw_file_id": "an_01H...", ...}
```

---

## 7. Streaming

- **OpenAI format:** Server-Sent Events (SSE), terminated by `data: [DONE]`.
- **Anthropic format:** a structured event sequence —
  `message_start` → `content_block_delta` → … → `message_stop`.

---

## 8. Agent / CLI integrations

The gateway is designed to slot in behind existing coding agents by overriding
their base URL.

### Claude Code (Anthropic CLI)
Via environment variables:
```bash
export ANTHROPIC_BASE_URL="https://api.atptoken.ai"
export ANTHROPIC_AUTH_TOKEN="atp-..."
export ANTHROPIC_API_KEY=""
export ANTHROPIC_MODEL="claude-sonnet-4-6"
```
Or via `~/.claude/settings.json`:
```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.atptoken.ai",
    "ANTHROPIC_AUTH_TOKEN": "atp-...",
    "ANTHROPIC_API_KEY": ""
  },
  "model": "claude-sonnet-4-6"
}
```

### Codex CLI (OpenAI-compatible)
`~/.codex/config.toml`:
```toml
model = "gpt-5.4"
model_provider = "atp"

[model_providers.atp]
name = "ATP"
base_url = "https://api.atptoken.ai/v1"
env_key = "ATP_API_KEY"
wire_api = "chat"
```
```bash
export ATP_API_KEY="atp-..."
```

---

## 9. Billing & credits

- **Unit:** 1 credit = **USD $0.01**.
- **Model:** pay-as-you-go, **non-expiring** credits.
- **Charging:** usage-based on **input + output tokens**.
- **Top-up packages:** from **$5 → 500 credits** up to **$1,000 → 100,000 credits**.

---

## 10. Error handling

| HTTP | Meaning |
|------|---------|
| `400` | Malformed request |
| `401` | Invalid / expired key |
| `402` | Insufficient credits |
| `403` | Model not enabled for the project |
| `429` | Rate limited |
| `502` / `503` | Upstream provider unavailable |

---

## 11. Console (dashboard) features

- **Usage Analytics** — per-model, per-key token tracking.
- **Request Logs** — filterable audit trail by time, model, status.
- **Activity Log** — security events (sign-ins, invites, quota changes).
- **Team Management** — Owner / Admin / Member roles per workspace/project.

---

## 12. Documentation navigation

- **Getting Started** — Quickstart, Model Discovery, Authentication, Agents
- **Using the Console** — Setup, Resources, Keys, Team, Monitoring
- **Billing & Credits** — How Credits Work, Pricing, Top-up, Spend Tracking
- **API Reference** — all endpoints
- **Streaming** — format specifications
- **Operational** — error codes

---

## Summary

atptoken.ai is a **drop-in LLM gateway**: point any of the three major provider
SDKs (or their CLIs like Claude Code / Codex) at `api.atptoken.ai`, authenticate
with a single `atp-…` key, and consume OpenAI / Anthropic / Gemini models against
one shared pool of pay-as-you-go credits. Access is governed by a four-level
Organization → Workspace → Project → Key hierarchy, with per-project model
allowlists, usage analytics, and standard HTTP error semantics.
