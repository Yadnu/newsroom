"""The gateway: routing, HTTP calls, retries, structured output, cost and latency accounting.

Providers are reached over plain HTTP (httpx), so no provider SDK is needed:
- chat: Groq's OpenAI-compatible ``/chat/completions`` (decision 0008)
- embeddings: Voyage ``/embeddings`` (decision 0007)
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.db.models import EMBEDDING_DIM
from app.log import get_logger
from app.shared.llm.schema import strict_json_schema
from app.shared.llm.types import (
    TASK_NAMES,
    EmbedInputType,
    LLMConfigError,
    LLMProviderError,
    Message,
    StructuredOutputError,
    TaskName,
    Usage,
)

RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
EMBED_BATCH = 1000  # Voyage max inputs per request
STRUCTURED_ATTEMPTS = 2  # resample once when the output fails validation
_MAX_BACKOFF_S = 30.0

log = get_logger(__name__)


def cost_usd(prices: dict[str, tuple[float, float]], model: str, t_in: int, t_out: int) -> float:
    try:
        price_in, price_out = prices[model]
    except KeyError:
        raise LLMConfigError(f"no price configured for model {model!r}") from None
    return (t_in * price_in + t_out * price_out) / 1_000_000


class Gateway:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._s = settings
        self._sleep = sleep
        self._http = httpx.AsyncClient(timeout=settings.llm_timeout_s, transport=transport)
        missing = [t for t in TASK_NAMES if t not in settings.llm_routes]
        if missing:
            raise LLMConfigError(f"llm_routes has no model for tasks: {missing}")
        for model in {*settings.llm_routes.values(), settings.embedding_model}:
            if model not in settings.llm_prices:
                raise LLMConfigError(f"no price configured for model {model!r}")

    async def aclose(self) -> None:
        await self._http.aclose()

    def model_for(self, task: TaskName) -> str:
        try:
            return self._s.llm_routes[task]
        except KeyError:
            raise LLMConfigError(f"unknown task {task!r}") from None

    # ---- chat -------------------------------------------------------------------------

    async def complete[T: BaseModel](
        self, task: TaskName, messages: Sequence[Message], schema: type[T]
    ) -> tuple[T, Usage]:
        model = self.model_for(task)
        key = self._key(self._s.groq_api_key, "NEWSROOM_GROQ_API_KEY")
        body = {
            "model": model,
            "messages": list(messages),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": strict_json_schema(schema),
                },
            },
        }
        start = time.perf_counter()
        t_in = t_out = attempts = 0
        last_err: Exception | None = None
        try:
            for _ in range(STRUCTURED_ATTEMPTS):
                try:
                    data, n = await self._post(
                        f"{self._s.groq_base_url}/chat/completions", key, body
                    )
                except LLMProviderError as e:
                    # Groq rejects schema-invalid generations with 400 json_validate_failed.
                    if e.status_code == 400 and "json_validate_failed" in str(e):
                        attempts += 1
                        last_err = e
                        continue
                    raise
                attempts += n
                usage = data.get("usage") or {}
                t_in += int(usage.get("prompt_tokens", 0))
                t_out += int(usage.get("completion_tokens", 0))
                try:
                    content = data["choices"][0]["message"]["content"]
                    return schema.model_validate_json(content), self._usage(
                        model, t_in, t_out, start, attempts, task=task
                    )
                except (KeyError, IndexError, TypeError, ValidationError) as e:
                    last_err = e
            raise StructuredOutputError(
                f"{model} gave no valid {schema.__name__} after {STRUCTURED_ATTEMPTS} tries"
            ) from last_err
        except Exception as e:
            log.warning("llm.call_failed", task=task, model=model, error=type(e).__name__)
            raise

    # ---- embeddings -------------------------------------------------------------------

    async def embed(
        self, texts: Sequence[str], input_type: EmbedInputType | None = "document"
    ) -> tuple[list[list[float]], Usage]:
        model = self._s.embedding_model
        if not texts:
            return [], Usage(model, 0, 0, 0.0, 0.0, 0)
        key = self._key(self._s.voyage_api_key, "NEWSROOM_VOYAGE_API_KEY")
        start = time.perf_counter()
        vectors: list[list[float]] = []
        tokens = attempts = 0
        for i in range(0, len(texts), EMBED_BATCH):
            batch = list(texts[i : i + EMBED_BATCH])
            body = {
                "model": model,
                "input": batch,
                "input_type": input_type,
                "output_dimension": EMBEDDING_DIM,
            }
            data, n = await self._post(f"{self._s.voyage_base_url}/embeddings", key, body)
            attempts += n
            tokens += int((data.get("usage") or {}).get("total_tokens", 0))
            rows = sorted(data["data"], key=lambda r: r["index"])
            if len(rows) != len(batch):
                raise LLMProviderError(f"asked for {len(batch)} embeddings, got {len(rows)}")
            for row in rows:
                vec = [float(x) for x in row["embedding"]]
                if len(vec) != EMBEDDING_DIM:
                    raise LLMProviderError(f"embedding has {len(vec)} dims, want {EMBEDDING_DIM}")
                vectors.append(vec)
        return vectors, self._usage(model, tokens, 0, start, attempts, task="embed")

    # ---- internals --------------------------------------------------------------------

    @staticmethod
    def _key(secret: Any, env_name: str) -> str:
        if secret is None:
            raise LLMConfigError(f"{env_name} is not set")
        value: str = secret.get_secret_value()
        return value

    async def _post(self, url: str, key: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """POST with retries on transient failures. Returns (json, attempts used)."""
        headers = {"Authorization": f"Bearer {key}"}
        for attempt in range(1, self._s.llm_max_attempts + 1):
            last = attempt == self._s.llm_max_attempts
            try:
                resp = await self._http.post(url, json=body, headers=headers)
            except httpx.TransportError as e:
                if last:
                    raise LLMProviderError(f"transport error: {type(e).__name__}") from e
                await self._sleep(self._backoff(attempt, None))
                continue
            if resp.status_code < 400:
                payload: dict[str, Any] = resp.json()
                return payload, attempt
            if resp.status_code in RETRYABLE_STATUS and not last:
                await self._sleep(self._backoff(attempt, resp.headers.get("retry-after")))
                continue
            raise LLMProviderError(
                f"HTTP {resp.status_code}: {_error_text(resp)}", status_code=resp.status_code
            )
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), _MAX_BACKOFF_S)
            except ValueError:
                pass
        return min(0.5 * 2.0 ** (attempt - 1), _MAX_BACKOFF_S)

    def _usage(
        self, model: str, t_in: int, t_out: int, start: float, attempts: int, *, task: str
    ) -> Usage:
        usage = Usage(
            model=model,
            tokens_in=t_in,
            tokens_out=t_out,
            cost_usd=cost_usd(self._s.llm_prices, model, t_in, t_out),
            latency_ms=(time.perf_counter() - start) * 1000,
            attempts=attempts,
        )
        log.info(
            "llm.call",
            task=task,
            model=model,
            tokens_in=t_in,
            tokens_out=t_out,
            cost_usd=usage.cost_usd,
            latency_ms=round(usage.latency_ms, 1),
            attempts=attempts,
        )
        return usage


def _error_text(resp: httpx.Response) -> str:
    """Provider error message only; never echoes request headers."""
    try:
        err = resp.json().get("error", {})
        if isinstance(err, dict):
            return f"{err.get('code', '')} {err.get('message', '')}".strip()[:500]
        return str(err)[:500]
    except (json.JSONDecodeError, AttributeError):
        return resp.text[:500]
