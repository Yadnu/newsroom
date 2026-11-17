"""``span()``: time one component step and record it as a ``traces`` row.

    with span("reporter", "ingest.feed", feed=url) as s:
        ...
        s.set(new_sources=12)

Spans nest through a context variable: an inner span gets the outer span as ``parent_id`` and
inherits its ``briefing_id``. Emitting never raises into the caller (decision 0005).
"""

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from app.archive.sink import get_sink
from app.db.models import Trace, utcnow
from app.log import get_logger

MAX_ERROR_CHARS = 2000

log = get_logger(__name__)
_current: ContextVar["Span | None"] = ContextVar("archive_current_span", default=None)


@dataclass(slots=True)
class Span:
    component: str
    event: str
    briefing_id: UUID | None = None
    parent_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(default_factory=utcnow)
    payload: dict[str, Any] = field(default_factory=dict)
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: float | None = None
    error: str | None = None

    def set(self, **payload: Any) -> None:
        """Add fields to the span payload (stored as JSONB)."""
        self.payload.update(payload)

    def add_usage(self, tokens_in: int = 0, tokens_out: int = 0, cost_usd: float = 0.0) -> None:
        """Accumulate LLM usage. Called by the llm-gateway; safe to call several times."""
        self.tokens_in = (self.tokens_in or 0) + tokens_in
        self.tokens_out = (self.tokens_out or 0) + tokens_out
        self.cost_usd = (self.cost_usd or 0.0) + cost_usd

    def to_trace(self) -> Trace:
        return Trace(
            id=self.id,
            briefing_id=self.briefing_id,
            parent_id=self.parent_id,
            component=self.component,
            event=self.event,
            started_at=self.started_at,
            latency_ms=self.latency_ms,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            cost_usd=self.cost_usd,
            error=self.error,
            payload=_json_safe(self.payload),
        )


def current_span() -> Span | None:
    return _current.get()


@contextmanager
def span(
    component: str, event: str, briefing_id: UUID | None = None, **payload: Any
) -> Iterator[Span]:
    parent = _current.get()
    if briefing_id is None and parent is not None:
        briefing_id = parent.briefing_id
    s = Span(
        component=component,
        event=event,
        briefing_id=briefing_id,
        parent_id=parent.id if parent else None,
        payload=dict(payload),
    )
    token = _current.set(s)
    start = time.perf_counter()
    try:
        yield s
    except BaseException as e:
        s.error = f"{type(e).__name__}: {e}"[:MAX_ERROR_CHARS]
        raise
    finally:
        _current.reset(token)
        s.latency_ms = (time.perf_counter() - start) * 1000
        try:
            get_sink().emit(s.to_trace())
        except Exception as e:  # tracing must never fail the main path
            log.warning("archive.emit_failed", component=component, error=type(e).__name__)


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(json.dumps(payload, default=str))
    return out
