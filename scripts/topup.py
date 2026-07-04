"""Admin CLI: add credits to a workspace.

Usage:
    uv run python scripts/topup.py --workspace <workspace_id> --credits 50
"""

from __future__ import annotations

import argparse
import asyncio

from gateway import billing, db
from gateway.models import Workspace


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--credits", type=float, required=True)
    args = parser.parse_args()

    async with db.get_sessionmaker()() as s:
        ws = await s.get(Workspace, args.workspace)
        if ws is None:
            raise SystemExit(f"Workspace {args.workspace} not found")
        await billing.top_up(
            s,
            workspace_id=args.workspace,
            credits_micros=int(args.credits * 1_000_000),
            reason="topup:cli",
        )
        await s.refresh(ws)
        print(f"New balance: {ws.credit_micros / 1_000_000:.2f} credits")


if __name__ == "__main__":
    asyncio.run(main())
