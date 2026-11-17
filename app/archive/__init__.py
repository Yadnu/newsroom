"""Archive: observability and claim-to-source traces.

Node: context/nodes/archive.md

Every component step runs inside ``span(component, event, briefing_id)``. Finished spans go to the
installed sink; the default ``DbSink`` writes them to ``traces`` in the background. Long-running
processes call ``await start_archive()`` at startup and ``await stop_archive()`` at shutdown.
"""

from app.archive.sink import DbSink, MemorySink, TraceSink, get_sink, set_sink
from app.archive.span import Span, current_span, span

__all__ = [
    "DbSink",
    "MemorySink",
    "Span",
    "TraceSink",
    "current_span",
    "get_sink",
    "set_sink",
    "span",
    "start_archive",
    "stop_archive",
]


async def start_archive() -> None:
    sink = get_sink()
    if isinstance(sink, DbSink):
        sink.start()


async def stop_archive() -> None:
    sink = get_sink()
    if isinstance(sink, DbSink):
        await sink.stop()
