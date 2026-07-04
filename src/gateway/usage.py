"""Extract (input_tokens, output_tokens) from provider responses.

Each provider reports usage differently. We trust the upstream numbers rather
than tokenizing ourselves (Phase 1 decision).
"""

from __future__ import annotations

from typing import Any


def from_openai(body: dict[str, Any]) -> tuple[int, int]:
    u = body.get("usage") or {}
    return int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))


def from_anthropic(body: dict[str, Any]) -> tuple[int, int]:
    u = body.get("usage") or {}
    return int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))


def from_gemini(body: dict[str, Any]) -> tuple[int, int]:
    u = body.get("usageMetadata") or {}
    prompt = int(u.get("promptTokenCount", 0))
    # Gemini reports total; candidates = total - prompt when not given directly.
    candidates = int(
        u.get("candidatesTokenCount", max(0, int(u.get("totalTokenCount", 0)) - prompt))
    )
    return prompt, candidates


def from_openai_stream_chunk(chunk: dict[str, Any]) -> tuple[int, int] | None:
    """OpenAI streaming sends a final chunk with ``usage`` when requested."""
    u = chunk.get("usage")
    if not u:
        return None
    return int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
