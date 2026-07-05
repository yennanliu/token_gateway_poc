import pytest
from sqlalchemy import select

from gateway import db
from gateway.models import ApiKey, Project, Workspace


@pytest.mark.asyncio
async def test_seed_roundtrip(seed):
    async with db.get_sessionmaker()() as s:
        ws = await s.get(Workspace, seed["workspace_id"])
        assert ws.credit_micros == 100_000_000
        proj = await s.get(Project, seed["project_id"])
        assert proj.workspace_id == ws.id
        key = await s.scalar(select(ApiKey).where(ApiKey.id == seed["api_key_id"]))
        assert key.key_prefix.startswith("gw-")
        # raw key is never stored
        assert seed["raw_key"] not in (key.key_hash, key.key_prefix)


@pytest.mark.asyncio
async def test_balance_defaults_to_zero(session):
    ws = Workspace(name="Empty")
    session.add(ws)
    await session.commit()
    fresh = await session.get(Workspace, ws.id)
    assert fresh.credit_micros == 0
