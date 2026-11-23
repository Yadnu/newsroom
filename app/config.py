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


# v1 topic scope default: AI and tech news (STATE open question).
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
    # Added 2026-11-18 (all returned 200 with entries) so the same event shows up in 2+ outlets.
    FeedConfig(url="https://arstechnica.com/ai/feed/", outlet="Ars Technica"),
    FeedConfig(
        url="https://www.theregister.com/software/ai_ml/headlines.atom", outlet="The Register"
    ),
    FeedConfig(url="https://www.engadget.com/rss.xml", outlet="Engadget"),
    FeedConfig(url="https://www.zdnet.com/topic/artificial-intelligence/rss.xml", outlet="ZDNET"),
    FeedConfig(
        url="https://www.theguardian.com/technology/artificialintelligenceai/rss",
        outlet="The Guardian",
    ),
    FeedConfig(
        url="https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
        outlet="The New York Times",
    ),
    FeedConfig(url="https://siliconangle.com/category/ai/feed/", outlet="SiliconANGLE"),
    FeedConfig(url="https://the-decoder.com/feed/", outlet="The Decoder"),
    FeedConfig(url="https://www.cnbc.com/id/19854910/device/rss/rss.html", outlet="CNBC"),
    FeedConfig(url="https://feeds.bloomberg.com/technology/news.rss", outlet="Bloomberg"),
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
    # Embedding batches and pacing (decision 0015). 0 = no limit. A Voyage key without billing
    # allows about 3 requests and 10K tokens per minute: use 3 / 9000 / 9000 there.
    embed_requests_per_minute: int = Field(default=0, ge=0)
    embed_tokens_per_minute: int = Field(default=0, ge=0)
    embed_batch_max_tokens: int = Field(default=100_000, ge=1)

    # Chat completions (decision 0008): Groq, OpenAI-compatible API.
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    # Second chat host (decision 0025): a model string "openrouter:<model id>" goes to OpenRouter.
    # Without a key, routes and fallbacks that name it are skipped (no judge fallback).
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
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
    # Task -> fallback model, tried once when the routed model gives invalid output twice or a
    # transient error outlives the retries (decision 0014). The judge falls back only to the same
    # model on a second host, never a weaker one (decision 0025), and only when that host has a
    # key. With a usable fallback, a 429 fails over at once instead of retrying.
    # Env override is JSON.
    llm_fallbacks: dict[str, str] = Field(
        default_factory=lambda: {
            "draft": "openai/gpt-oss-120b",
            "classify": "openai/gpt-oss-120b",
            "answer": "openai/gpt-oss-120b",
            "judge": "openrouter:openai/gpt-oss-120b",
        }
    )
    # Model -> (input, output) USD per 1M tokens. Groq list prices 2026-11-16; free tier bills $0
    # but we record list cost so budgets hold after upgrading. Voyage price unconfirmed (0007).
    llm_prices: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {
            "openai/gpt-oss-20b": (0.075, 0.30),
            "openai/gpt-oss-120b": (0.15, 0.60),
            # OpenRouter's price depends on the host it picks; about this on 2026-11-23.
            "openrouter:openai/gpt-oss-120b": (0.04, 0.18),
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
    # Langfuse export of LLM calls (decision 0005). Off unless both keys are set.
    langfuse_capture_content: bool = True  # send prompts and outputs; false = usage only
    langfuse_flush_interval_s: float = Field(default=5.0, gt=0)
    langfuse_batch_size: int = Field(default=50, ge=1, le=500)

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
    # Live search for answers (task 5.4, decision 0021): Tavily, Firecrawl for full text.
    reporter_search_days: int = Field(default=7, ge=1, le=30)
    reporter_search_max_results: int = Field(default=5, ge=1, le=20)
    reporter_search_min_chars: int = Field(default=1200, ge=0)  # shorter -> fetch with Firecrawl
    reporter_fetch_max_chars: int = Field(default=20000, ge=1000)
    reporter_search_trust: float = Field(default=0.5, ge=0.0, le=1.0)
    reporter_search_cache_s: int = Field(default=600, ge=0)
    reporter_search_timeout_s: float = Field(default=8.0, gt=0)
    # Recheck of cited sources for retractions (task 6.2, decision 0023).
    reporter_recheck_hours: int = Field(default=48, ge=1)
    reporter_recheck_max: int = Field(default=200, ge=1)

    # Standards Desk air gate (task 4.1, decision 0016).
    standards_max_copied_words: int = Field(default=12, ge=5)
    standards_max_transition_words: int = Field(default=10, ge=1)
    standards_max_question_words: int = Field(default=80, ge=5)  # caller screen (task 5.2)
    standards_max_corrections: int = Field(default=3, ge=0)  # per briefing (task 6.2)

    # Anchor voice output (task 4.2, decisions 0004 and 0017).
    anchor_tts: Literal["cartesia", "fake"] = "cartesia"
    cartesia_voice_id: str | None = None
    cartesia_model: str | None = None  # None: Pipecat's default Cartesia model
    anchor_sample_rate: int = Field(default=24000, ge=8000, le=48000)
    anchor_line_gap_ms: int = Field(default=300, ge=0)
    anchor_send_ahead_ms: int = Field(default=250, ge=0)  # client buffer for realtime sessions
    anchor_line_timeout_s: float = Field(default=30.0, gt=0)

    # Caller voice input (task 5.1, decisions 0004 and 0018).
    caller_stt: Literal["deepgram", "fake"] = "deepgram"
    deepgram_model: str = "nova-3"
    caller_sample_rate: int = Field(default=16000, ge=8000, le=48000)
    caller_utterance_gap_ms: int = Field(default=800, ge=100)
    caller_max_question_s: int = Field(default=30, ge=1, le=120)
    caller_finalize_wait_ms: int = Field(default=1500, ge=0)  # after release, for the last words

    # Producer rundown (task 2.0).
    producer_freshness_hours: int = Field(default=24, ge=1)
    producer_min_sources: int = Field(default=2, ge=1)
    producer_seconds_per_story: int = Field(default=45, ge=10)
    # Answering listener questions (task 5.3, decision 0020).
    producer_answer_budget_s: float = Field(
        default=8.0, gt=0
    )  # logged as over_budget when exceeded
    producer_answer_timeout_s: float = Field(default=12.0, gt=0)  # then the safe line is spoken
    producer_answer_max_sources: int = Field(default=6, ge=1)
    producer_answer_max_lines: int = Field(default=3, ge=1, le=6)
    producer_answer_source_max_chars: int = Field(default=3000, ge=500)
    producer_answer_search: bool = True  # live search when the briefing's sources fall short
    producer_answer_search_timeout_s: float = Field(default=20.0, gt=0)  # answer limit with search

    # Writer (task 2.1). ~150 spoken words per minute.
    writer_words_per_second: float = Field(default=2.5, gt=0)
    writer_source_max_chars: int = Field(default=6000, ge=500)

    # Editor (task 2.2, decision 0012). Evidence chunks are embedded on the fly, not stored.
    editor_chunk_chars: int = Field(default=700, ge=200)
    editor_chunk_overlap: int = Field(default=120, ge=0)
    editor_source_max_chars: int = Field(default=20000, ge=1000)
    editor_top_k: int = Field(default=4, ge=1, le=12)
    editor_max_concurrency: int = Field(default=8, ge=1)
    # Rewrite loop (task 2.3, decision 0013): rounds of Writer rewrites for non-approved claims.
    rewrite_max_rounds: int = Field(default=2, ge=0, le=5)


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings, read once. Tests call ``get_settings.cache_clear()``."""
    return Settings()
