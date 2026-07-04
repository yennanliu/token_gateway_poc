"""FastAPI application: wires routers, error handling, and the console."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from . import admin
from .db import create_all
from .errors import GatewayError, gateway_error_handler
from .routers import anthropic, gemini, models, openai
from .upstream import close_client

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all()
    yield
    await close_client()


def create_app() -> FastAPI:
    app = FastAPI(title="Token Gateway", version="0.1.0", lifespan=lifespan)

    app.add_exception_handler(GatewayError, gateway_error_handler)

    # Provider-compatible proxy endpoints
    app.include_router(models.router)
    app.include_router(openai.router)
    app.include_router(anthropic.router)
    app.include_router(gemini.router)

    # Console API
    app.include_router(admin.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/")
    async def console():
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return {"status": "ok", "console": "frontend/index.html not found"}

    return app


app = create_app()
