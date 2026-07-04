"""OpenAI-compatible endpoint: POST /v1/chat/completions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import errors, proxy, usage
from ..config import get_settings
from ..db import get_session
from ..upstream import openai_upstream

router = APIRouter()
STYLE = "openai"


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, session: AsyncSession = Depends(get_session)):
    raw, body = await proxy._parse_body(request, STYLE)
    model = body.get("model")
    if not model:
        raise errors.bad_request("Missing 'model'.", STYLE)

    # Phase 4: OpenAI-format client calling an Anthropic model → translate.
    if get_settings().enable_translation and model.startswith("claude"):
        return await proxy.handle_translated(
            request, session, endpoint="chat.completions", style=STYLE, model=model, body=body
        )

    return await proxy.handle(
        request,
        session,
        endpoint="chat.completions",
        style=STYLE,
        model=model,
        raw=raw,
        upstream=openai_upstream("/chat/completions"),
        usage_of=usage.from_openai,
        stream=bool(body.get("stream")),
        stream_usage_of=proxy.openai_stream_usage,
    )
