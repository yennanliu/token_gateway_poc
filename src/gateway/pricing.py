"""Model pricing.

Rates are in **micros per token** (1_000_000 micros = 1 credit = $0.01).
Example: $3.00 / 1M input tokens = 300 credits / 1M tokens
         = 300 * 1_000_000 micros / 1_000_000 tokens = 300 micros/token.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rate:
    input_micros_per_token: int
    output_micros_per_token: int


# Illustrative published-style rates (adjust to real provider pricing).
PRICING: dict[str, Rate] = {
    # OpenAI-style
    "gpt-5.4": Rate(250, 1000),
    "gpt-4o": Rate(250, 1000),
    "gpt-4o-mini": Rate(15, 60),
    # Anthropic-style
    "claude-sonnet-4-6": Rate(300, 1500),
    "claude-opus-4-8": Rate(1500, 7500),
    "claude-haiku-4-5": Rate(80, 400),
    # Gemini-style
    "gemini-2.5-pro": Rate(125, 500),
    "gemini-2.5-flash": Rate(30, 120),
}

# Fallback rate for unknown models so we never bill zero by accident.
DEFAULT_RATE = Rate(300, 1500)


def rate_for(model_id: str) -> Rate:
    return PRICING.get(model_id, DEFAULT_RATE)


def cost_micros(model_id: str, input_tokens: int, output_tokens: int) -> int:
    r = rate_for(model_id)
    return input_tokens * r.input_micros_per_token + output_tokens * r.output_micros_per_token
