"""Application configuration loaded from environment / .env (Pydantic settings).

Fails fast with a clear, secret-free message when required values are missing.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Discord
    discord_token: str = Field(..., min_length=1)
    guild_id: int
    owner_discord_id: int | None = None

    # Database (Supabase Postgres)
    database_url: str = Field(..., min_length=1)
    migration_database_url: str | None = None

    # Verification (external verification bot -> Audience)
    verified_source_role_id: int | None = None

    # Behavior
    upload_max_mb: int = 8
    recruit_timeout_minutes: int = 120
    log_level: str = "INFO"

    @property
    def effective_migration_url(self) -> str:
        """URL used by Alembic; falls back to the runtime DATABASE_URL."""
        return self.migration_database_url or self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings, raising a friendly error on misconfiguration."""
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        missing = ", ".join(str(err["loc"][0]) for err in exc.errors())
        raise SystemExit(
            "Configuration error: missing or invalid settings "
            f"[{missing}]. Copy .env.example to .env and fill in the values. "
            "(Secrets are never printed.)"
        ) from None
