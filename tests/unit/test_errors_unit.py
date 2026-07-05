"""Unit tests for provider-shaped error envelopes."""

from gateway import errors


def test_openai_error_shape():
    body = errors.render_error(402, "insufficient_credits", "no money", "openai")
    assert body == {"error": {"message": "no money", "type": "insufficient_credits", "code": "insufficient_credits"}}


def test_anthropic_error_shape():
    body = errors.render_error(401, "invalid_api_key", "bad key", "anthropic")
    assert body == {"type": "error", "error": {"type": "invalid_api_key", "message": "bad key"}}


def test_gemini_error_shape():
    body = errors.render_error(403, "model_not_enabled", "nope", "gemini")
    assert body["error"]["code"] == 403
    assert body["error"]["status"] == "model_not_enabled"


def test_constructors_carry_status_and_style():
    e = errors.payment_required("anthropic")
    assert e.status == 402
    assert e.style == "anthropic"
    assert e.code == "insufficient_credits"

    f = errors.forbidden_model("gpt-4o", "openai")
    assert f.status == 403
    assert "gpt-4o" in f.message
