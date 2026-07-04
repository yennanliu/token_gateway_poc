"""Cross-provider translation (Phase 4).

Lets an OpenAI-format client call an Anthropic model: translate an OpenAI
``chat.completions`` request into an Anthropic ``messages`` request, and the
Anthropic response back into an OpenAI ``chat.completion``. Non-streaming only.
"""

from __future__ import annotations

from typing import Any


def openai_to_anthropic(body: dict[str, Any]) -> dict[str, Any]:
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []
    for m in body.get("messages", []):
        role = m.get("role")
        content = m.get("content", "")
        if role == "system":
            if isinstance(content, str):
                system_parts.append(content)
            continue
        # Anthropic roles: user / assistant
        messages.append({"role": role, "content": content})

    out: dict[str, Any] = {
        "model": body["model"],
        "messages": messages,
        "max_tokens": int(body.get("max_tokens") or 1024),
    }
    if system_parts:
        out["system"] = "\n".join(system_parts)
    for k in ("temperature", "top_p", "stop_sequences"):
        if k in body:
            out[k] = body[k]
    return out


def anthropic_to_openai(resp: dict[str, Any], model: str) -> dict[str, Any]:
    text = "".join(
        block.get("text", "")
        for block in resp.get("content", [])
        if block.get("type") == "text"
    )
    stop_reason = resp.get("stop_reason")
    finish = "stop" if stop_reason in ("end_turn", "stop_sequence", None) else "length"
    usage = resp.get("usage", {})
    return {
        "id": "chatcmpl-" + str(resp.get("id", "translated")),
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish,
            }
        ],
        "usage": {
            "prompt_tokens": int(usage.get("input_tokens", 0)),
            "completion_tokens": int(usage.get("output_tokens", 0)),
            "total_tokens": int(usage.get("input_tokens", 0))
            + int(usage.get("output_tokens", 0)),
        },
    }
