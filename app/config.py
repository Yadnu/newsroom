"""Application settings. The only place that reads the environment.

Values come from env vars (prefix ``NEWSROOM_``) or a local ``.env`` file. Secrets are
``SecretStr`` so they never show up in reprs or logs.
"""

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class FeedConfig(BaseModel):
    url: str
    outlet: str = Field(max_length=200)
    trust_score: float = Field(default=0.5, ge=0.0, le=1.0)


# v1 topic scope default: AI and tech news (STATE open question). All checked reachable 2026-11-16.
# Trust scores are a uniform 0.5 placeholder until the Editor calibrates them.
DEFAULT_FEEDS = (
    FeedConfig(
        url="https://feeds.arstechnica.com/arstechnica/technology-lab", outlet="Ars Technica"
    ),
    FeedConfig(
        url="https://techcrunch.com/category/artificial-intelligence/feed/", outlet="TechCrunch"
    ),
    FeedConfig(
        url="https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", outlet="The Verge"
    ),
    FeedConfig(url="https://www.technologyreview.com/feed/", outlet="MIT Technology Review"),
    FeedConfig(url="https://www.wired.com/feed/tag/ai/latest/rss", outlet="Wired"),
    FeedConfig(url="https://feeds.bbci.co.uk/news/technology/rss.xml", outlet="BBC News"),
)


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

    # Reporter RSS ingest (decision 0003).
    # Feeds override as a JSON list of {url, outlet, trust_score}.
    reporter_feeds: list[FeedConfig] = Field(default_factory=lambda: list(DEFAULT_FEEDS))
    reporter_ingest_every_minutes: int = Field(default=15, ge=1, le=60)
    reporter_fetch_timeout_s: float = 20.0
    reporter_max_concurrency: int = 8
    reporter_user_agent: str = "newsroom-bot/0.1"
    # Clustering (decision 0010). Threshold is uncalibrated until a labelled live sample exists.
    reporter_cluster_threshold: float = Field(default=0.80, gt=0.0, le=1.0)
    reporter_cluster_window_hours: int = Field(default=24, ge=1)
    reporter_embed_max_chars: int = 8000

    # Producer rundown (task 2.0).
    producer_freshness_hours: int = Field(default=24, ge=1)
    producer_min_sources: int = Field(default=2, ge=1)
    producer_seconds_per_story: int = Field(default=45, ge=10)

    # Writer (task 2.1). ~150 spoken words per minute.
    writer_words_per_second: float = Field(default=2.5, gt=0)
    writer_source_max_chars: int = Field(default=6000, ge=500)

    # Editor (task 2.2, decision 0012). Evidence chunks are embedded on the fly, not stored.
    editor_chunk_chars: int = Field(default=700, ge=200)
    editor_chunk_overlap: int = Field(default=120, ge=0)
    editor_source_max_chars: int = Field(default=20000, ge=1000)
    editor_top_k: int = Field(default=4, ge=1, le=12)
    editor_max_concurrency: int = Field(default=8, ge=1)


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings, read once. Tests call ``get_settings.cache_clear()``."""
    return Settings()
