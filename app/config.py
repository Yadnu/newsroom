"""Application settings. The only place that reads the environment.

Values come from env vars (prefix ``NEWSROOM_``) or a local ``.env`` file. Secrets are
``SecretStr`` so they never show up in reprs or logs.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEWSROOM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    database_url: str = "postgresql+asyncpg://newsroom:newsroom@localhost:5432/newsroom"
    redis_url: str = "redis://localhost:6379/0"

    # External services from the decided stack. Optional until the task that uses them.
    deepgram_api_key: SecretStr | None = None
    cartesia_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    exa_api_key: SecretStr | None = None
    firecrawl_api_key: SecretStr | None = None
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings, read once. Tests call ``get_settings.cache_clear()``."""
    return Settings()
