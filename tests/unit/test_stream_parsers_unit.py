"""Unit tests for SSE usage parsers (pure functions over raw bytes)."""

from gateway import proxy


def test_openai_stream_usage():
    data = (
        b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
        b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":8}}\n\n'
        b"data: [DONE]\n\n"
    )
    assert proxy.openai_stream_usage(data) == (12, 8)


def test_openai_stream_usage_absent():
    data = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'
    assert proxy.openai_stream_usage(data) == (0, 0)


def test_openai_stream_ignores_malformed_lines():
    data = b"data: not-json\n\ndata: {\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":2}}\n\n"
    assert proxy.openai_stream_usage(data) == (1, 2)


def test_anthropic_stream_usage():
    data = (
        b'data: {"type":"message_start","message":{"usage":{"input_tokens":6,"output_tokens":0}}}\n\n'
        b'data: {"type":"content_block_delta","delta":{"text":"hi"}}\n\n'
        b'data: {"type":"message_delta","usage":{"output_tokens":5}}\n\n'
        b'data: {"type":"message_stop"}\n\n'
    )
    assert proxy.anthropic_stream_usage(data) == (6, 5)
