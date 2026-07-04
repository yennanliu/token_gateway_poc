"""Application configuration (env-driven via pydantic-settings).

Phase 1 keeps things simple: one settings object, read from the environment
(and an optional `.env` file). SQLite is the default DB so the gateway runs
with zero external services; set ``DATABASE_URL`` to a Postgres DSN in prod.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Database -----------------------------------------------------------
    # Default: local SQLite file. Prod: postgresql+asyncpg://user:pass@host/db
    database_url: str = "sqlite+aiosqlite:///./gateway.db"

    # --- Upstream provider credentials (the REAL keys the gateway injects) --
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_version: str = "2023-06-01"

    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    # --- Admin / console ----------------------------------------------------
    # Token required to call the /admin/* endpoints (the console uses it).
    admin_token: str = "dev-admin-token"

    # --- Rate limiting (Phase 2) -------------------------------------------
    # Default requests-per-minute per API key (0 = unlimited). Individual keys
    # can override via ApiKey.rpm_limit.
    default_rpm_limit: int = 0

    # --- Payments (Phase 2) -------------------------------------------------
    # If a Stripe secret key is set, real Checkout sessions are created;
    # otherwise the payments module runs in "mock" mode and top-ups apply
    # credits immediately.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # 1 credit = 1 cent (USD). Micros give integer precision: 1e6 micros = 1 credit.
    micros_per_credit: int = 1_000_000
    cents_per_credit: int = 1  # 1 credit == $0.01


@lru_cache
def get_settings() -> Settings:
    return Settings()
