"""Application configuration via Pydantic BaseSettings.

Loads env vars (or a `.env` file at repo root) once and exposes them
through a typed `Settings` instance. Accessed via `get_settings()`.

Adding new config: append a field to the Settings class. Tests can
override by patching env vars then calling `get_settings.cache_clear()`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from env vars and/or a `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    neon_database_url: SecretStr | None = Field(
        default=None,
        description=(
            "Neon Postgres connection URL with sslmode=require. "
            "Optional at settings level: db.py raises RuntimeError on actual "
            "connection attempt if None; tests skip via is_configured()."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton.

    Testing: call ``get_settings.cache_clear()`` after monkeypatching
    env vars to force a fresh load.
    """
    return Settings()
