"""Unit tests for the in-process metrics registry."""

import pytest

from gateway import metrics


@pytest.fixture(autouse=True)
def _reset():
    metrics.reset()
    yield
    metrics.reset()


def test_counters_and_prometheus_render():
    metrics.record_request("chat.completions", "gpt-5.4", 200)
    metrics.record_request("chat.completions", "gpt-5.4", 200)
    metrics.record_request("messages", "claude-sonnet-4-6", 402)
    metrics.record_tokens("gpt-5.4", 100, 50)

    text = metrics.render_prometheus()
    assert 'gateway_requests_total{endpoint="chat.completions",model="gpt-5.4",status="200"} 2' in text
    assert 'gateway_requests_total{endpoint="messages",model="claude-sonnet-4-6",status="402"} 1' in text
    assert 'gateway_input_tokens_total{model="gpt-5.4"} 100' in text
    assert 'gateway_output_tokens_total{model="gpt-5.4"} 50' in text


def test_reset_clears():
    metrics.record_request("x", "m", 200)
    metrics.reset()
    snap = metrics.snapshot()
    assert snap["requests"] == {}
    assert snap["tokens_in"] == {}
