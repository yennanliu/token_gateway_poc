"""Shared test fixtures.

- In-memory SQLite (StaticPool so all sessions share one connection).
- An httpx AsyncClient bound to the ASGI app (ASGITransport is NOT intercepted
  by respx, so respx only mocks the gateway's *upstream* calls).
- A seeded workspace/project/key with a known raw key value.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

# Configure env BEFORE settings are first read.
os.environ.update(
    {
        "OPENAI_API_KEY": "real-openai-key",
        "ANTHROPIC_API_KEY": "real-anthropic-key",
        "GEMINI_API_KEY": "real-gemini-key",
        "ADMIN_TOKEN": "test-admin-token",
        "DEFAULT_RPM_LIMIT": "0",
        "STRIPE_SECRET_KEY": "",
    }
)

from gateway import db, metrics  # noqa: E402
from gateway.config import get_settings  # noqa: E402
from gateway.keys import display_prefix, generate_key, hash_key  # noqa: E402
from gateway.main import create_app  # noqa: E402
from gateway.models import ApiKey, Project, ProjectModel, Workspace  # noqa: E402
from gateway import ratelimit  # noqa: E402

get_settings.cache_clear()

ADMIN_TOKEN = "test-admin-token"


def pytest_collection_modifyitems(config, items):
    """Auto-tag tests by location: tests/unit/* -> unit, everything else -> integration."""
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)
        else:
            item.add_marker(pytest.mark.integration)


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.configure_engine(eng)
    await db.create_all()
    ratelimit.use_in_memory()
    metrics.reset()
    get_settings.cache_clear()
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def app(engine):
    return create_app()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def session(engine):
    async with db.get_sessionmaker()() as s:
        yield s


@pytest_asyncio.fixture
async def seed(engine):
    """Create a workspace (with credits), a project, an enabled model, and a key.

    Returns a dict with ids and the RAW key string.
    """
    raw_key = generate_key()
    async with db.get_sessionmaker()() as s:
        ws = Workspace(name="Acme", credit_micros=100_000_000)  # 100 credits
        s.add(ws)
        await s.flush()
        proj = Project(workspace_id=ws.id, name="prod")
        s.add(proj)
        await s.flush()
        s.add(ProjectModel(project_id=proj.id, model_id="gpt-5.4"))
        s.add(ProjectModel(project_id=proj.id, model_id="claude-sonnet-4-6"))
        s.add(ProjectModel(project_id=proj.id, model_id="gemini-2.5-pro"))
        key = ApiKey(
            project_id=proj.id,
            name="default",
            key_prefix=display_prefix(raw_key),
            key_hash=hash_key(raw_key),
        )
        s.add(key)
        await s.commit()
        return {
            "workspace_id": ws.id,
            "project_id": proj.id,
            "api_key_id": key.id,
            "raw_key": raw_key,
        }
