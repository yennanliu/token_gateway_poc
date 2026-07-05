"""Admin CLI: mint a workspace + project + API key.

Usage:
    uv run python scripts/create_key.py \
        --workspace "Acme" --project "prod" \
        --models gpt-5.4 claude-sonnet-4-6 gemini-2.5-pro \
        --credits 100

Prints the raw ``gw-…`` key ONCE (it is not recoverable afterwards).
"""

from __future__ import annotations

import argparse
import asyncio

from gateway import db
from gateway.keys import display_prefix, generate_key, hash_key
from gateway.models import ApiKey, Project, ProjectModel, Workspace


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default="Default Workspace")
    parser.add_argument("--project", default="default")
    parser.add_argument("--models", nargs="*", default=["gpt-5.4", "claude-sonnet-4-6"])
    parser.add_argument("--credits", type=float, default=0.0)
    parser.add_argument("--name", default="default")
    args = parser.parse_args()

    await db.create_all()
    raw = generate_key()
    async with db.get_sessionmaker()() as s:
        ws = Workspace(
            name=args.workspace, credit_micros=int(args.credits * 1_000_000)
        )
        s.add(ws)
        await s.flush()
        proj = Project(workspace_id=ws.id, name=args.project)
        s.add(proj)
        await s.flush()
        for m in args.models:
            s.add(ProjectModel(project_id=proj.id, model_id=m))
        key = ApiKey(
            project_id=proj.id,
            name=args.name,
            key_prefix=display_prefix(raw),
            key_hash=hash_key(raw),
        )
        s.add(key)
        await s.commit()

        print("Workspace ID:", ws.id)
        print("Project ID:  ", proj.id)
        print("Models:      ", ", ".join(args.models))
        print("Credits:     ", args.credits)
        print()
        print("API KEY (shown once):")
        print("   ", raw)


if __name__ == "__main__":
    asyncio.run(main())
