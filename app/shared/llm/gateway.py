"""The gateway: routing, HTTP calls, retries, structured output, cost and latency accounting.

Providers are reached over plain HTTP (httpx), so no provider SDK is needed:
- chat: Groq's OpenAI-compatible ``/chat/completions`` (decision 0008)
- embeddings: Voyage ``/embeddings`` (decision 0007)

Each call is also exported to Langfuse when keys are set (decision 0005, ``langfuse.py``).
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from app.archive import Span, current_span, span
from app.config import Settings
from app.db.models import EMBEDDING_DIM
from app.log import get_logger
from app.shared.llm.langfuse import Langfuse
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
EMBED_CHARS_PER_TOKEN = 3  # conservative estimate for sizing batches before the call
STRUCTURED_ATTEMPTS = 2  # resample once when the output fails validation
_MAX_BACKOFF_S = 30.0
_RATE_LIMIT_BACKOFF_S = 15.0

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
        clock: Callable[[], float] = time.monotonic,
        langfuse: Langfuse | None = None,
    ) -> None:
        self._s = settings
        self.langfuse = langfuse if langfuse is not None else Langfuse(settings)
        self._sleep = sleep
        self._clock = clock
        # Embedding pacing (decision 0015): one request at a time, next start no earlier than this.
        self._embed_lock = asyncio.Lock()
        self._embed_next_at = 0.0
        self._http = httpx.AsyncClient(timeout=settings.llm_timeout_s, transport=transport)
        missing = [t for t in TASK_NAMES if t not in settings.llm_routes]
        if missing:
            raise LLMConfigError(f"llm_routes has no model for tasks: {missing}")
        for model in {
            *settings.llm_routes.values(),
            *settings.llm_fallbacks.values(),
            settings.embedding_model,
        }:
            if model not in settings.llm_prices:
                raise LLMConfigError(f"no price configured for model {model!r}")

    async def aclose(self) -> None:
        await self.langfuse.aclose()
        await self._http.aclose()

    def model_for(self, task: TaskName) -> str:
        try:
            return self._s.llm_routes[task]
        except KeyError:
            raise LLMConfigError(f"unknown task {task!r}") from None

    # ---- chat -------------------------------------------------------------------------

    def fallback_for(self, task: TaskName) -> str | None:
        return self._s.llm_fallbacks.get(task)

    async def complete[T: BaseModel](
        self, task: TaskName, messages: Sequence[Message], schema: type[T]
    ) -> tuple[T, Usage]:
        """Call the task's model. If it fails with invalid output or a provider error that
        survived the retries, try the task's fallback model once (decision 0014)."""
        with span("llm-gateway", f"complete.{task}", schema=schema.__name__) as s:
            model = self.model_for(task)
            s.set(model=model)
            self._lf_trace(s, schema=schema.__name__, task=task)
            fallback = self.fallback_for(task)
            try:
                result, usage = await self._complete(task, messages, schema, model)
            except (StructuredOutputError, LLMProviderError) as e:
                if fallback is None or not _fallback_worthy(e):
                    raise
                log.warning(
                    "llm.fallback",
                    task=task,
                    model=model,
                    fallback=fallback,
                    error=type(e).__name__,
                )
                s.set(fallback_from=model, fallback_reason=type(e).__name__, model=fallback)
                result, usage = await self._complete(task, messages, schema, fallback)
            _record(s, usage)
            return result, usage

    async def _complete[T: BaseModel](
        self, task: TaskName, messages: Sequence[Message], schema: type[T], model: str
    ) -> tuple[T, Usage]:
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
        started_at = datetime.now(UTC)
        t_in = t_out = attempts = 0
        content: str | None = None
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
                    parsed = schema.model_validate_json(content)
                except (KeyError, IndexError, TypeError, ValidationError) as e:
                    last_err = e
                    continue
                usage = self._usage(model, t_in, t_out, start, attempts, task=task)
                self._lf_chat(task, model, started_at, messages, content, usage)
                return parsed, usage
            raise StructuredOutputError(
                f"{model} gave no valid {schema.__name__} after {STRUCTURED_ATTEMPTS} tries"
            ) from last_err
        except Exception as e:
            log.warning("llm.call_failed", task=task, model=model, error=type(e).__name__)
            failed = Usage(model, t_in, t_out, self._cost(model, t_in, t_out) or 0.0, 0.0, attempts)
            self._lf_chat(task, model, started_at, messages, content, failed, error=e)
            raise

    # ---- embeddings -------------------------------------------------------------------

    async def embed(
        self, texts: Sequence[str], input_type: EmbedInputType | None = "document"
    ) -> tuple[list[list[float]], Usage]:
        model = self._s.embedding_model
        with span("llm-gateway", "embed", model=model, n_texts=len(texts)) as s:
            if not texts:
                vectors, usage = await self._embed(texts, input_type)
                _record(s, usage)
                return vectors, usage
            self._lf_trace(s, n_texts=len(texts))
            started_at = datetime.now(UTC)
            meta = {"n_texts": len(texts), "input_type": input_type}  # counts only, never texts
            try:
                vectors, usage = await self._embed(texts, input_type)
            except Exception as e:
                self._lf_generation(s.id, "embed", model, started_at, meta, None, 0, 0, None, e)
                raise
            _record(s, usage)
            self._lf_generation(
                s.id, "embed", model, started_at, meta, None, usage.tokens_in, 0, usage.cost_usd
            )
            return vectors, usage

    async def _embed(
        self, texts: Sequence[str], input_type: EmbedInputType | None
    ) -> tuple[list[list[float]], Usage]:
        model = self._s.embedding_model
        if not texts:
            return [], Usage(model, 0, 0, 0.0, 0.0, 0)
        key = self._key(self._s.voyage_api_key, "NEWSROOM_VOYAGE_API_KEY")
        start = time.perf_counter()
        vectors: list[list[float]] = []
        tokens = attempts = 0
        for batch in embed_batches(texts, self._batch_token_cap()):
            body = {
                "model": model,
                "input": batch,
                "input_type": input_type,
                "output_dimension": EMBEDDING_DIM,
            }
            async with self._embed_lock:
                await self._wait_embed_slot()
                sent_at = self._clock()
                data, n = await self._post(f"{self._s.voyage_base_url}/embeddings", key, body)
                used = int((data.get("usage") or {}).get("total_tokens", 0))
                self._embed_next_at = sent_at + self._embed_interval(
                    used or sum(estimate_tokens(t) for t in batch)
                )
            attempts += n
            tokens += used
            rows = sorted(data["data"], key=lambda r: r["index"])
            if len(rows) != len(batch):
                raise LLMProviderError(f"asked for {len(batch)} embeddings, got {len(rows)}")
            for row in rows:
                vec = [float(x) for x in row["embedding"]]
                if len(vec) != EMBEDDING_DIM:
                    raise LLMProviderError(f"embedding has {len(vec)} dims, want {EMBEDDING_DIM}")
                vectors.append(vec)
        return vectors, self._usage(model, tokens, 0, start, attempts, task="embed")

    def _batch_token_cap(self) -> int:
        cap = self._s.embed_batch_max_tokens
        if self._s.embed_tokens_per_minute:
            cap = min(cap, self._s.embed_tokens_per_minute)
        return cap

    def _embed_interval(self, tokens: int) -> float:
        """Seconds to wait after a request so neither per-minute limit is exceeded."""
        rpm, tpm = self._s.embed_requests_per_minute, self._s.embed_tokens_per_minute
        return max(60.0 / rpm if rpm else 0.0, 60.0 * tokens / tpm if tpm else 0.0)

    async def _wait_embed_slot(self) -> None:
        delay = self._embed_next_at - self._clock()
        if delay > 0:
            await self._sleep(delay)

    # ---- Langfuse export (decision 0005) -----------------------------------------------

    def _lf_trace(self, s: Span, **metadata: Any) -> None:
        self.langfuse.trace(
            s.id, s.event, briefing_id=s.briefing_id, parent_span_id=s.parent_id, metadata=metadata
        )

    def _lf_chat(
        self,
        task: str,
        model: str,
        started_at: datetime,
        messages: Sequence[Message],
        content: str | None,
        usage: Usage,
        error: Exception | None = None,
    ) -> None:
        s = current_span()
        if s is None or not self.langfuse.enabled:
            return
        self._lf_generation(
            s.id,
            f"complete.{task}",
            model,
            started_at,
            self.langfuse.chat_input(messages),
            self.langfuse.chat_output(content) if content is not None else None,
            usage.tokens_in,
            usage.tokens_out,
            usage.cost_usd,
            error,
            attempts=usage.attempts,
        )

    def _lf_generation(
        self,
        trace_id: UUID,
        name: str,
        model: str,
        started_at: datetime,
        input: Any,
        output: Any,
        tokens_in: int,
        tokens_out: int,
        cost: float | None,
        error: Exception | None = None,
        **metadata: Any,
    ) -> None:
        self.langfuse.generation(
            trace_id,
            name,
            model=model,
            start=started_at,
            end=datetime.now(UTC),
            input=input,
            output=output,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            metadata=metadata,
            error=f"{type(error).__name__}: {error}"[:500] if error else None,
        )

    def _cost(self, model: str, t_in: int, t_out: int) -> float | None:
        try:
            return cost_usd(self._s.llm_prices, model, t_in, t_out)
        except LLMConfigError:
            return None

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
                await self._sleep(
                    self._backoff(attempt, resp.headers.get("retry-after"), resp.status_code)
                )
                continue
            raise LLMProviderError(
                f"HTTP {resp.status_code}: {_error_text(resp)}", status_code=resp.status_code
            )
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None, status: int | None = None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), _MAX_BACKOFF_S)
            except ValueError:
                pass
        if status == 429:
            # Per-minute limits with no retry-after: wait long enough for the window to roll.
            return min(_RATE_LIMIT_BACKOFF_S * attempt, _MAX_BACKOFF_S)
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


def _fallback_worthy(e: Exception) -> bool:
    """Invalid output, or a transient provider failure. Not auth or bad-request errors."""
    if isinstance(e, StructuredOutputError):
        return True
    return isinstance(e, LLMProviderError) and (
        e.status_code is None or e.status_code in RETRYABLE_STATUS
    )


def _record(s: Span, usage: Usage) -> None:
    s.add_usage(usage.tokens_in, usage.tokens_out, usage.cost_usd)
    s.set(attempts=usage.attempts)


def _error_text(resp: httpx.Response) -> str:
    """Provider error message only; never echoes request headers."""
    try:
        err = resp.json().get("error", {})
        if isinstance(err, dict):
            return f"{err.get('code', '')} {err.get('message', '')}".strip()[:500]
        return str(err)[:500]
    except (json.JSONDecodeError, AttributeError):
        return resp.text[:500]


def estimate_tokens(text: str) -> int:
    return max(1, -(-len(text) // EMBED_CHARS_PER_TOKEN))


def embed_batches(texts: Sequence[str], max_tokens: int) -> list[list[str]]:
    """Split in order into batches of at most ``EMBED_BATCH`` texts and ``max_tokens`` estimated
    tokens. A single text over the cap goes alone (the caller already trims texts)."""
    batches: list[list[str]] = []
    batch: list[str] = []
    size = 0
    for text in texts:
        n = estimate_tokens(text)
        if batch and (len(batch) >= EMBED_BATCH or size + n > max_tokens):
            batches.append(batch)
            batch, size = [], 0
        batch.append(text)
        size += n
    if batch:
        batches.append(batch)
    return batches
