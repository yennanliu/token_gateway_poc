"""Upstream provider adapters + shared HTTP client.

Each adapter knows a provider's base URL, how to inject the *real* provider key,
and the target path. Phase 1 is pass-through: the client's request body is
forwarded verbatim; only the auth header and host change.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import get_settings

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(600.0))
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class Upstream:
    """Resolved upstream target: URL + headers with the real key injected."""

    def __init__(self, url: str, headers: dict[str, str]) -> None:
        self.url = url
        self.headers = headers


def openai_upstream(path: str) -> Upstream:
    s = get_settings()
    return Upstream(
        url=f"{s.openai_base_url.rstrip('/')}{path}",
        headers={
            "authorization": f"Bearer {s.openai_api_key}",
            "content-type": "application/json",
        },
    )


def anthropic_upstream(path: str) -> Upstream:
    s = get_settings()
    return Upstream(
        url=f"{s.anthropic_base_url.rstrip('/')}{path}",
        headers={
            "x-api-key": s.anthropic_api_key,
            "anthropic-version": s.anthropic_version,
            "content-type": "application/json",
        },
    )


def gemini_upstream(path: str) -> Upstream:
    s = get_settings()
    return Upstream(
        url=f"{s.gemini_base_url.rstrip('/')}{path}",
        headers={
            "x-goog-api-key": s.gemini_api_key,
            "content-type": "application/json",
        },
    )


async def forward_json(up: Upstream, body: bytes) -> httpx.Response:
    return await get_client().post(up.url, content=body, headers=up.headers)


async def forward_stream(up: Upstream, body: bytes) -> AsyncIterator[bytes]:
    """Yield raw bytes from a streaming upstream response."""
    async with get_client().stream(
        "POST", up.url, content=body, headers=up.headers
    ) as resp:
        async for chunk in resp.aiter_bytes():
            yield chunk


async def get_json(up: Upstream) -> httpx.Response:
    return await get_client().get(up.url, headers=up.headers)
