"""Where finished spans go.

``DbSink`` buffers traces in memory and a background task writes them to Postgres in batches, so
``emit()`` never waits on the database. When the buffer is full the oldest traces are dropped
(and counted) instead of blocking. A failed batch is retried row by row so one bad row only
loses itself.
"""

import asyncio
import contextlib
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from app.db.models import Trace
from app.db.session import session_scope
from app.log import get_logger

log = get_logger(__name__)

WriteBatch = Callable[[Sequence[Trace]], Awaitable[None]]


class TraceSink(Protocol):
    def emit(self, trace: Trace) -> None: ...


class MemorySink:
    """Keeps traces in a list. For tests and local debugging."""

    def __init__(self) -> None:
        self.traces: list[Trace] = []

    def emit(self, trace: Trace) -> None:
        self.traces.append(trace)


async def write_to_db(traces: Sequence[Trace]) -> None:
    async with session_scope() as session:
        session.add_all(traces)


class DbSink:
    def __init__(
        self,
        write: WriteBatch = write_to_db,
        max_buffer: int = 10_000,
        batch_size: int = 200,
        flush_interval_s: float = 0.5,
    ) -> None:
        self._write = write
        self._buffer: deque[Trace] = deque()
        self._max_buffer = max_buffer
        self._batch_size = batch_size
        self._interval = flush_interval_s
        self._task: asyncio.Task[None] | None = None
        self.dropped = 0
        self.written = 0

    def emit(self, trace: Trace) -> None:
        if len(self._buffer) >= self._max_buffer:
            self._buffer.popleft()
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 1000 == 0:
                log.warning("archive.buffer_full", dropped=self.dropped)
        self._buffer.append(trace)

    @property
    def pending(self) -> int:
        return len(self._buffer)

    def start(self) -> None:
        """Start the background writer on the running event loop."""
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        """Stop the writer and flush what is left."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.flush()

    async def flush(self) -> None:
        while self._buffer:
            n = min(self._batch_size, len(self._buffer))
            batch = [self._buffer.popleft() for _ in range(n)]
            await self._write_safely(batch)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self.flush()

    async def _write_safely(self, batch: list[Trace]) -> None:
        try:
            await self._write(batch)
            self.written += len(batch)
            return
        except Exception as e:
            if len(batch) == 1:
                self.dropped += 1
                log.warning(
                    "archive.write_failed", error=type(e).__name__, trace_event=batch[0].event
                )
                return
        for trace in batch:  # isolate the bad rows
            await self._write_safely([trace])


_sink: TraceSink = DbSink()


def get_sink() -> TraceSink:
    return _sink


def set_sink(sink: TraceSink) -> TraceSink:
    """Install a sink and return the previous one."""
    global _sink
    previous, _sink = _sink, sink
    return previous
