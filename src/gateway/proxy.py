"""Shared proxy flow used by every provider router.

Non-streaming: forward → read upstream ``usage`` → bill + log → return.
Streaming: tee bytes to the client while parsing usage out of the event stream;
bill + log when the stream closes (even on client disconnect).
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from . import auth, billing, errors, logs
from .db import get_sessionmaker
from .upstream import Upstream, forward_json, forward_stream

UsageExtractor = Callable[[dict[str, Any]], tuple[int, int]]
StreamUsageParser = Callable[[bytes], tuple[int, int]]


def _now_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


async def _parse_body(request: Request, style: errors.Style) -> tuple[bytes, dict]:
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise errors.bad_request("Request body is not valid JSON.", style)
    if not isinstance(body, dict):
        raise errors.bad_request("Request body must be a JSON object.", style)
    return raw, body


async def handle(
    request: Request,
    session: AsyncSession,
    *,
    endpoint: str,
    style: errors.Style,
    model: str,
    raw: bytes,
    upstream: Upstream,
    usage_of: UsageExtractor,
    stream: bool,
    stream_usage_of: StreamUsageParser | None = None,
):
    """Guarded proxy. ``model`` and ``raw`` are pre-parsed by the router."""
    start = time.monotonic()
    ctx = await auth.guard(request, session, model=model, style=style)

    if stream and stream_usage_of is not None:
        return _stream_response(
            ctx=ctx,
            endpoint=endpoint,
            model=model,
            raw=raw,
            upstream=upstream,
            stream_usage_of=stream_usage_of,
            start=start,
        )

    try:
        resp = await forward_json(upstream, raw)
    except httpx.HTTPError:
        await logs.record_request(
            session,
            endpoint=endpoint,
            status=502,
            latency_ms=_now_ms(start),
            api_key_id=ctx.api_key.id,
            project_id=ctx.project.id,
            model_id=model,
        )
        raise errors.upstream_unavailable(style)

    if resp.status_code >= 400:
        await logs.record_request(
            session,
            endpoint=endpoint,
            status=resp.status_code,
            latency_ms=_now_ms(start),
            api_key_id=ctx.api_key.id,
            project_id=ctx.project.id,
            model_id=model,
        )
        return JSONResponse(status_code=resp.status_code, content=_safe_json(resp))

    data = resp.json()
    in_tok, out_tok = usage_of(data)
    await billing.record_usage_and_debit(
        session,
        workspace_id=ctx.workspace.id,
        api_key_id=ctx.api_key.id,
        project_id=ctx.project.id,
        model_id=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        status=resp.status_code,
    )
    await logs.record_request(
        session,
        endpoint=endpoint,
        status=resp.status_code,
        latency_ms=_now_ms(start),
        api_key_id=ctx.api_key.id,
        project_id=ctx.project.id,
        model_id=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )
    return JSONResponse(status_code=resp.status_code, content=data)


def _stream_response(
    *,
    ctx: auth.AuthContext,
    endpoint: str,
    model: str,
    raw: bytes,
    upstream: Upstream,
    stream_usage_of: StreamUsageParser,
    start: float,
) -> StreamingResponse:
    async def gen() -> AsyncIterator[bytes]:
        collected = bytearray()
        try:
            async for chunk in forward_stream(upstream, raw):
                collected.extend(chunk)
                yield chunk
        finally:
            in_tok, out_tok = stream_usage_of(bytes(collected))
            # Fresh session: the request-scoped session is gone by now.
            async with get_sessionmaker()() as s:
                await billing.record_usage_and_debit(
                    s,
                    workspace_id=ctx.workspace.id,
                    api_key_id=ctx.api_key.id,
                    project_id=ctx.project.id,
                    model_id=model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                )
                await logs.record_request(
                    s,
                    endpoint=endpoint,
                    status=200,
                    latency_ms=_now_ms(start),
                    api_key_id=ctx.api_key.id,
                    project_id=ctx.project.id,
                    model_id=model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                )

    return StreamingResponse(gen(), media_type="text/event-stream")


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"error": {"message": resp.text, "type": "upstream_error"}}


# --- Streaming usage parsers -------------------------------------------------


def openai_stream_usage(data: bytes) -> tuple[int, int]:
    """OpenAI SSE: a chunk carries ``usage`` when stream_options.include_usage."""
    for line in data.splitlines():
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if payload in (b"[DONE]", b""):
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        u = obj.get("usage")
        if u:
            return int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
    return 0, 0


def anthropic_stream_usage(data: bytes) -> tuple[int, int]:
    """Anthropic SSE: input_tokens in message_start, output_tokens in message_delta."""
    in_tok = 0
    out_tok = 0
    for line in data.splitlines():
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "message_start":
            u = obj.get("message", {}).get("usage", {})
            in_tok = int(u.get("input_tokens", in_tok))
            out_tok = int(u.get("output_tokens", out_tok))
        elif obj.get("type") == "message_delta":
            u = obj.get("usage", {})
            if "output_tokens" in u:
                out_tok = int(u["output_tokens"])
    return in_tok, out_tok
