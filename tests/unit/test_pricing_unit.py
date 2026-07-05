"""Unit tests for pricing math."""

from gateway import pricing


def test_cost_micros_known_model():
    r = pricing.rate_for("gpt-5.4")
    cost = pricing.cost_micros("gpt-5.4", 100, 50)
    assert cost == 100 * r.input_micros_per_token + 50 * r.output_micros_per_token


def test_unknown_model_uses_default_rate():
    assert pricing.rate_for("no-such-model") is pricing.DEFAULT_RATE
    cost = pricing.cost_micros("no-such-model", 10, 10)
    d = pricing.DEFAULT_RATE
    assert cost == 10 * d.input_micros_per_token + 10 * d.output_micros_per_token


def test_zero_tokens_zero_cost():
    assert pricing.cost_micros("gpt-5.4", 0, 0) == 0


def test_output_costs_more_than_input():
    r = pricing.rate_for("claude-sonnet-4-6")
    assert r.output_micros_per_token > r.input_micros_per_token
