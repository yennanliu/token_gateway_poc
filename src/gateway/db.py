"""Async SQLAlchemy engine + session management.

Works with both SQLite (default, dev/test) and Postgres (prod) by keeping the
column types portable (see ``models.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, future=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


def configure_engine(engine: AsyncEngine) -> None:
    """Override the engine (used by tests to inject an in-memory DB)."""
    global _engine, _sessionmaker
    _engine = engine
    _sessionmaker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session (commit/rollback handled by callers)."""
    async with get_sessionmaker()() as session:
        yield session


async def create_all() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
