"""In-process metrics (Phase 4), exposed at /metrics in Prometheus text format.

Process-local counters — good enough for a single-instance POC. For multi-instance
use a real Prometheus client + aggregation.
"""

from __future__ import annotations

from collections import defaultdict

_requests: dict[tuple[str, str, int], int] = defaultdict(int)  # (endpoint, model, status)
_tokens_in: dict[str, int] = defaultdict(int)  # model
_tokens_out: dict[str, int] = defaultdict(int)  # model


def record_request(endpoint: str, model: str, status: int) -> None:
    _requests[(endpoint, model or "-", status)] += 1


def record_tokens(model: str, input_tokens: int, output_tokens: int) -> None:
    _tokens_in[model] += input_tokens
    _tokens_out[model] += output_tokens


def reset() -> None:
    _requests.clear()
    _tokens_in.clear()
    _tokens_out.clear()


def snapshot() -> dict:
    return {
        "requests": dict(_requests),
        "tokens_in": dict(_tokens_in),
        "tokens_out": dict(_tokens_out),
    }


def render_prometheus() -> str:
    lines: list[str] = []
    lines.append("# HELP gateway_requests_total Proxy requests by endpoint/model/status.")
    lines.append("# TYPE gateway_requests_total counter")
    for (endpoint, model, status), n in sorted(_requests.items()):
        lines.append(
            f'gateway_requests_total{{endpoint="{endpoint}",model="{model}",status="{status}"}} {n}'
        )
    lines.append("# HELP gateway_input_tokens_total Input tokens by model.")
    lines.append("# TYPE gateway_input_tokens_total counter")
    for model, n in sorted(_tokens_in.items()):
        lines.append(f'gateway_input_tokens_total{{model="{model}"}} {n}')
    lines.append("# HELP gateway_output_tokens_total Output tokens by model.")
    lines.append("# TYPE gateway_output_tokens_total counter")
    for model, n in sorted(_tokens_out.items()):
        lines.append(f'gateway_output_tokens_total{{model="{model}"}} {n}')
    return "\n".join(lines) + "\n"
