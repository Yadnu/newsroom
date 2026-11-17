"""Application settings. The only place that reads the environment.

Values come from env vars (prefix ``NEWSROOM_``) or a local ``.env`` file. Secrets are
``SecretStr`` so they never show up in reprs or logs.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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

    # Embeddings (decision 0007). The vector dimension is fixed in the schema, not here.
    embedding_model: str = "voyage-4-lite"
    voyage_api_key: SecretStr | None = None
    voyage_base_url: str = "https://api.voyageai.com/v1"

    # Chat completions (decision 0008): Groq, OpenAI-compatible API.
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_timeout_s: float = 60.0
    llm_max_attempts: int = 4
    # Task -> model (decision 0002). Env override is JSON: NEWSROOM_LLM_ROUTES='{"judge": "..."}'.
    llm_routes: dict[str, str] = Field(
        default_factory=lambda: {
            "draft": "openai/gpt-oss-20b",
            "classify": "openai/gpt-oss-20b",
            "answer": "openai/gpt-oss-20b",
            "judge": "openai/gpt-oss-120b",
        }
    )
    # Model -> (input, output) USD per 1M tokens. Groq list prices 2026-11-16; free tier bills $0
    # but we record list cost so budgets hold after upgrading. Voyage price unconfirmed (0007).
    llm_prices: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {
            "openai/gpt-oss-20b": (0.075, 0.30),
            "openai/gpt-oss-120b": (0.15, 0.60),
            "voyage-4-lite": (0.02, 0.0),
        }
    )

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
