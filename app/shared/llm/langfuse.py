"""Langfuse export of LLM calls for prompt debugging (decision 0005, task 3.2).

The product trace stays in our ``traces`` table. This sends a developer copy of each gateway call to
Langfuse's public ingestion API (``POST /api/public/ingestion``) over plain httpx, no SDK:

- one Langfuse trace per gateway call; its id is the archive span id (``complete.<task>`` or
  ``embed``), so a Langfuse trace maps to a ``traces`` row. ``sessionId`` is the briefing id.
- one generation per model tried (primary, then fallback), with messages, raw output, tokens and
  cost. Embedding generations carry counts only, never the texts.

Events are buffered and sent in batches from a background task. Export never raises into the
caller and never logs keys (decision 0005: tracing must not fail the main path). With no keys
configured it is a no-op.
"""

import asyncio
import contextlib
import json
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx

from app.config import Settings
from app.log import get_logger

INGESTION_PATH = "/api/public/ingestion"
MAX_FIELD_CHARS = 20_000  # per message / output, keeps events well under Langfuse's size limit
MAX_BUFFER = 2_000  # events; the oldest are dropped if Langfuse is unreachable for long

log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _clip(text: str) -> str:
    return text if len(text) <= MAX_FIELD_CHARS else text[:MAX_FIELD_CHARS] + "...[truncated]"


def _output(content: str) -> Any:
    """Structured output as JSON when it parses, else the (clipped) raw text."""
    if len(content) <= MAX_FIELD_CHARS:
        try:
            return json.loads(content)
        except ValueError:
            pass
    return _clip(content)


class Langfuse:
    """Buffered, fire-and-forget Langfuse exporter. ``enabled`` is false without both keys."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        pk, sk = settings.langfuse_public_key, settings.langfuse_secret_key
        self._pk = pk.get_secret_value() if pk else ""
        self._sk = sk.get_secret_value() if sk else ""
        self.enabled = bool(self._pk and self._sk)
        self.capture_content = settings.langfuse_capture_content
        self._url = settings.langfuse_host.rstrip("/") + INGESTION_PATH
        self._interval = settings.langfuse_flush_interval_s
        self._batch = settings.langfuse_batch_size
        self._sleep = sleep
        self._buffer: deque[dict[str, Any]] = deque(maxlen=MAX_BUFFER)
        self._task: asyncio.Task[None] | None = None
        self._waiting = False
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    # ---- recording (sync, never raises) --------------------------------------------------

    def trace(
        self,
        trace_id: UUID,
        name: str,
        *,
        briefing_id: UUID | None,
        parent_span_id: UUID | None,
        metadata: dict[str, Any],
    ) -> None:
        self._add(
            "trace-create",
            {
                "id": str(trace_id),
                "name": name,
                "timestamp": _iso(_now()),
                "sessionId": str(briefing_id) if briefing_id else None,
                "metadata": {"parent_span_id": str(parent_span_id) if parent_span_id else None}
                | metadata,
                "tags": ["newsroom"],
            },
        )

    def generation(
        self,
        trace_id: UUID,
        name: str,
        *,
        model: str,
        start: datetime,
        end: datetime,
        input: Any,
        output: Any,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float | None,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        body: dict[str, Any] = {
            "id": str(uuid4()),
            "traceId": str(trace_id),
            "name": name,
            "model": model,
            "startTime": _iso(start),
            "endTime": _iso(end),
            "input": input if self.capture_content else None,
            "output": output if self.capture_content else None,
            "usageDetails": {"input": tokens_in, "output": tokens_out},
            "metadata": metadata or {},
            "level": "ERROR" if error else "DEFAULT",
            "statusMessage": error,
        }
        if cost_usd is not None:
            body["costDetails"] = {"total": cost_usd}
        self._add("generation-create", body)

    def chat_input(self, messages: Sequence[Any]) -> list[dict[str, str]]:
        return [{"role": str(m["role"]), "content": _clip(str(m["content"]))} for m in messages]

    chat_output = staticmethod(_output)

    def _add(self, kind: str, body: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            self._buffer.append(
                {"id": str(uuid4()), "timestamp": _iso(_now()), "type": kind, "body": body}
            )
            if self._task is None or self._task.done():
                self._task = asyncio.get_running_loop().create_task(self._flush_soon())
        except Exception as e:  # never fail the main path
            log.warning("langfuse.record_failed", error=type(e).__name__)

    # ---- sending -------------------------------------------------------------------------

    async def _flush_soon(self) -> None:
        if len(self._buffer) < self._batch:
            self._waiting = True
            try:
                await self._sleep(self._interval)
            finally:
                self._waiting = False
        await self.flush()

    async def flush(self) -> None:
        """Send everything buffered. Failures are logged (status only) and the batch dropped."""
        while self._buffer:
            n = min(len(self._buffer), self._batch)
            batch = [self._buffer.popleft() for _ in range(n)]
            try:
                if self._http is None:
                    self._http = httpx.AsyncClient(timeout=10.0, transport=self._transport)
                resp = await self._http.post(
                    self._url, json={"batch": batch}, auth=(self._pk, self._sk)
                )
                if resp.status_code >= 400:
                    log.warning("langfuse.send_failed", status=resp.status_code, events=n)
                elif resp.status_code == 207 and (errors := _errors(resp)):
                    log.warning("langfuse.events_rejected", events=n, rejected=errors)
            except Exception as e:
                log.warning("langfuse.send_failed", error=type(e).__name__, events=n)

    async def aclose(self) -> None:
        task = self._task
        if task is not None and not task.done():
            if self._waiting:  # only cancel the wait, never a send in flight
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self.flush()
        if self._http is not None:
            await self._http.aclose()
            self._http = None


def _errors(resp: httpx.Response) -> int:
    try:
        return len(resp.json().get("errors") or [])
    except (ValueError, AttributeError):
        return 0
