"""Error contract.

The gateway returns errors in the shape the *calling* SDK expects, so client
SDK error handling keeps working. ``GatewayError`` carries an HTTP status, a
short code, a message, and a ``style`` selecting the response envelope.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

Style = str  # "openai" | "anthropic" | "gemini"


class GatewayError(Exception):
    def __init__(
        self, status: int, code: str, message: str, style: Style = "openai"
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.style = style


def render_error(status: int, code: str, message: str, style: Style) -> dict:
    if style == "anthropic":
        return {"type": "error", "error": {"type": code, "message": message}}
    if style == "gemini":
        return {"error": {"code": status, "message": message, "status": code}}
    # default: OpenAI
    return {"error": {"message": message, "type": code, "code": code}}


async def gateway_error_handler(_: Request, exc: GatewayError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content=render_error(exc.status, exc.code, exc.message, exc.style),
    )


# Convenience constructors
def unauthorized(style: Style = "openai") -> GatewayError:
    return GatewayError(401, "invalid_api_key", "Invalid or missing API key.", style)


def payment_required(style: Style = "openai") -> GatewayError:
    return GatewayError(402, "insufficient_credits", "Insufficient credits.", style)


def forbidden_model(model: str, style: Style = "openai") -> GatewayError:
    return GatewayError(
        403, "model_not_enabled", f"Model '{model}' is not enabled for this project.", style
    )


def rate_limited(style: Style = "openai") -> GatewayError:
    return GatewayError(429, "rate_limited", "Rate limit exceeded.", style)


def bad_request(message: str, style: Style = "openai") -> GatewayError:
    return GatewayError(400, "invalid_request_error", message, style)


def upstream_unavailable(style: Style = "openai") -> GatewayError:
    return GatewayError(502, "upstream_error", "Upstream provider error.", style)
