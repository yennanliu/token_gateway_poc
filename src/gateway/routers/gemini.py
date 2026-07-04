"""Gemini-compatible endpoint: POST /v1/models/{model}:generateContent.

The model name is in the path (Google style). We also accept the streaming
variant ``:streamGenerateContent``.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import proxy, usage
from ..db import get_session
from ..upstream import gemini_upstream

router = APIRouter()
STYLE = "gemini"


def _gemini_stream_usage(data: bytes) -> tuple[int, int]:
    """Gemini stream is a JSON array of chunks; take the last usageMetadata seen."""
    in_tok = out_tok = 0
    text = data.decode("utf-8", errors="ignore")
    # Chunks may arrive as SSE-ish 'data: {...}' or a JSON array; scan objects.
    for frag in text.replace("data:", "\n").splitlines():
        frag = frag.strip().rstrip(",")
        if not frag.startswith("{"):
            continue
        try:
            obj = json.loads(frag)
        except json.JSONDecodeError:
            continue
        i, o = usage.from_gemini(obj)
        if i or o:
            in_tok, out_tok = i, o
    return in_tok, out_tok


@router.post("/v1/models/{model}:{action}")
async def generate_content(
    model: str, action: str, request: Request, session: AsyncSession = Depends(get_session)
):
    raw, _ = await proxy._parse_body(request, STYLE)
    is_stream = action == "streamGenerateContent"
    return await proxy.handle(
        request,
        session,
        endpoint="generateContent",
        style=STYLE,
        model=model,
        raw=raw,
        upstream=gemini_upstream(f"/models/{model}:{action}"),
        usage_of=usage.from_gemini,
        stream=is_stream,
        stream_usage_of=_gemini_stream_usage if is_stream else None,
    )
