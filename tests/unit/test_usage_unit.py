"""Unit tests for provider usage extraction."""

from gateway import usage


def test_from_openai():
    body = {"usage": {"prompt_tokens": 11, "completion_tokens": 7}}
    assert usage.from_openai(body) == (11, 7)


def test_from_openai_missing_usage():
    assert usage.from_openai({}) == (0, 0)


def test_from_anthropic():
    body = {"usage": {"input_tokens": 4, "output_tokens": 9}}
    assert usage.from_anthropic(body) == (4, 9)


def test_from_gemini_explicit_candidates():
    body = {"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 8, "totalTokenCount": 13}}
    assert usage.from_gemini(body) == (5, 8)


def test_from_gemini_derives_candidates_from_total():
    body = {"usageMetadata": {"promptTokenCount": 5, "totalTokenCount": 12}}
    assert usage.from_gemini(body) == (5, 7)


def test_openai_stream_chunk_with_and_without_usage():
    assert usage.from_openai_stream_chunk({"usage": {"prompt_tokens": 2, "completion_tokens": 3}}) == (2, 3)
    assert usage.from_openai_stream_chunk({"choices": []}) is None
