"""Anthropic-compatible endpoint: POST /v1/messages."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import errors, proxy, usage
from ..db import get_session
from ..upstream import anthropic_upstream

router = APIRouter()
STYLE = "anthropic"


@router.post("/v1/messages")
async def messages(request: Request, session: AsyncSession = Depends(get_session)):
    raw, body = await proxy._parse_body(request, STYLE)
    model = body.get("model")
    if not model:
        raise errors.bad_request("Missing 'model'.", STYLE)
    return await proxy.handle(
        request,
        session,
        endpoint="messages",
        style=STYLE,
        model=model,
        raw=raw,
        upstream=anthropic_upstream("/v1/messages"),
        usage_of=usage.from_anthropic,
        stream=bool(body.get("stream")),
        stream_usage_of=proxy.anthropic_stream_usage,
    )
