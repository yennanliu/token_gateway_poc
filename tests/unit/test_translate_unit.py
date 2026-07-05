"""Unit tests for OpenAI<->Anthropic translation edge cases."""

from gateway import translate


def test_no_system_message():
    body = {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]}
    out = translate.openai_to_anthropic(body)
    assert "system" not in out
    assert out["max_tokens"] == 1024


def test_explicit_max_tokens_and_temperature_passthrough():
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 256,
        "temperature": 0.4,
        "messages": [{"role": "user", "content": "hi"}],
    }
    out = translate.openai_to_anthropic(body)
    assert out["max_tokens"] == 256
    assert out["temperature"] == 0.4


def test_multiple_system_messages_joined():
    body = {
        "model": "claude-sonnet-4-6",
        "messages": [
            {"role": "system", "content": "a"},
            {"role": "system", "content": "b"},
            {"role": "user", "content": "hi"},
        ],
    }
    out = translate.openai_to_anthropic(body)
    assert out["system"] == "a\nb"


def test_finish_reason_maps_max_tokens_to_length():
    resp = {"content": [{"type": "text", "text": "x"}], "stop_reason": "max_tokens",
            "usage": {"input_tokens": 1, "output_tokens": 1}}
    out = translate.anthropic_to_openai(resp, "claude-sonnet-4-6")
    assert out["choices"][0]["finish_reason"] == "length"


def test_empty_content_yields_empty_string():
    resp = {"content": [], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 0}}
    out = translate.anthropic_to_openai(resp, "claude-sonnet-4-6")
    assert out["choices"][0]["message"]["content"] == ""
    assert out["usage"]["total_tokens"] == 1
