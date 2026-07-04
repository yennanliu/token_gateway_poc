"""Request-log recording (Phase 2 — powers the log UI and analytics)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .models import RequestLog


async def record_request(
    session: AsyncSession,
    *,
    endpoint: str,
    status: int,
    latency_ms: int,
    api_key_id: str | None = None,
    project_id: str | None = None,
    model_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    session.add(
        RequestLog(
            endpoint=endpoint,
            status=status,
            latency_ms=latency_ms,
            api_key_id=api_key_id,
            project_id=project_id,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    )
    await session.commit()
