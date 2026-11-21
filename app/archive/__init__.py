"""Archive: observability and claim-to-source traces.

Node: context/nodes/archive.md

Every component step runs inside ``span(component, event, briefing_id)``. Finished spans go to the
installed sink; the default ``DbSink`` writes them to ``traces`` in the background. Long-running
processes call ``await start_archive()`` at startup and ``await stop_archive()`` at shutdown.
"""

from app.archive.briefings import (
    BriefingDetail,
    BriefingNotFoundError,
    BriefingSummary,
    LineSummary,
    Stage,
    briefing_detail,
    list_briefings,
)
from app.archive.corrections import CorrectionRef, list_corrections
from app.archive.sink import DbSink, MemorySink, TraceSink, get_sink, set_sink
from app.archive.span import Span, current_span, span
from app.archive.trace import (
    ClaimTrace,
    EvidenceRef,
    Judgement,
    Rejection,
    SourceRef,
    TracedClaim,
    TraceNotFoundError,
    claim_trace,
    rejection_log,
)

__all__ = [
    "BriefingDetail",
    "BriefingNotFoundError",
    "BriefingSummary",
    "ClaimTrace",
    "CorrectionRef",
    "DbSink",
    "EvidenceRef",
    "Judgement",
    "LineSummary",
    "MemorySink",
    "Rejection",
    "SourceRef",
    "Span",
    "Stage",
    "TraceNotFoundError",
    "TraceSink",
    "TracedClaim",
    "briefing_detail",
    "claim_trace",
    "current_span",
    "get_sink",
    "list_briefings",
    "list_corrections",
    "rejection_log",
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
