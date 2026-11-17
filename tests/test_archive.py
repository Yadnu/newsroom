import asyncio
from collections.abc import Sequence
from uuid import uuid4

import httpx
import pytest

from app.archive import DbSink, MemorySink, current_span, set_sink, span
from app.config import Settings
from app.db.models import Trace
from app.shared.llm import Gateway, LLMProviderError

# ---- span ----------------------------------------------------------------------------------


def test_span_records_one_trace_with_latency_and_payload(trace_sink: MemorySink) -> None:
    bid = uuid4()
    with span("reporter", "ingest.feed", bid, feed="https://example.com/rss") as s:
        s.set(new_sources=3)

    (t,) = trace_sink.traces
    assert (t.component, t.event, t.briefing_id) == ("reporter", "ingest.feed", bid)
    assert t.payload == {"feed": "https://example.com/rss", "new_sources": 3}
    assert t.latency_ms is not None and t.latency_ms >= 0
    assert t.error is None and t.parent_id is None
    assert t.tokens_in is None and t.cost_usd is None
    assert t.started_at.tzinfo is not None


def test_nested_spans_link_parent_and_inherit_briefing(trace_sink: MemorySink) -> None:
    bid = uuid4()
    with span("producer", "build_rundown", bid) as outer:
        with span("writer", "draft_script") as inner:
            assert current_span() is inner
        assert current_span() is outer
    assert current_span() is None

    inner_t, outer_t = trace_sink.traces  # inner finishes first
    assert inner_t.parent_id == outer_t.id == outer.id
    assert inner_t.briefing_id == bid


def test_error_is_recorded_and_reraised(trace_sink: MemorySink) -> None:
    with pytest.raises(ValueError, match="bad feed"), span("reporter", "ingest.feed"):
        raise ValueError("bad feed")
    assert trace_sink.traces[0].error == "ValueError: bad feed"


def test_usage_accumulates() -> None:
    with span("editor", "judge_claim") as s:
        s.add_usage(10, 2, 0.001)
        s.add_usage(5, 1, 0.0005)
    assert (s.tokens_in, s.tokens_out) == (15, 3)
    assert s.cost_usd == pytest.approx(0.0015)


def test_payload_is_made_json_safe(trace_sink: MemorySink) -> None:
    sid = uuid4()
    with span("reporter", "dedupe", source_id=sid, tags={"a"}):
        pass
    payload = trace_sink.traces[0].payload
    assert payload["source_id"] == str(sid)
    assert isinstance(payload["tags"], str)


def test_broken_sink_never_fails_the_caller() -> None:
    class Broken:
        def emit(self, trace: Trace) -> None:
            raise RuntimeError("sink down")

    set_sink(Broken())
    with span("anchor", "speak"):
        result = 42
    assert result == 42


async def test_spans_in_concurrent_tasks_do_not_cross(trace_sink: MemorySink) -> None:
    async def job(name: str) -> None:
        with span("writer", name):
            await asyncio.sleep(0)
            with span("llm-gateway", f"{name}.inner"):
                await asyncio.sleep(0)

    await asyncio.gather(job("a"), job("b"))
    by_event = {t.event: t for t in trace_sink.traces}
    assert by_event["a.inner"].parent_id == by_event["a"].id
    assert by_event["b.inner"].parent_id == by_event["b"].id


# ---- DbSink ----------------------------------------------------------------------------------


class FakeDb:
    def __init__(self, bad_events: set[str] | None = None) -> None:
        self.rows: list[Trace] = []
        self.calls: list[int] = []
        self.bad = bad_events or set()

    async def __call__(self, traces: Sequence[Trace]) -> None:
        self.calls.append(len(traces))
        if any(t.event in self.bad for t in traces):
            raise RuntimeError("integrity error")
        self.rows.extend(traces)


def _trace(event: str = "e") -> Trace:
    return Trace(component="test", event=event)


async def test_dbsink_emit_does_not_write_until_flushed() -> None:
    db = FakeDb()
    sink = DbSink(write=db, batch_size=2)
    for _ in range(5):
        sink.emit(_trace())
    assert db.calls == [] and sink.pending == 5
    await sink.flush()
    assert db.calls == [2, 2, 1]
    assert sink.written == 5 and sink.pending == 0


async def test_dbsink_bad_row_only_drops_itself() -> None:
    db = FakeDb(bad_events={"bad"})
    sink = DbSink(write=db)
    for ev in ("ok1", "bad", "ok2"):
        sink.emit(_trace(ev))
    await sink.flush()
    assert [t.event for t in db.rows] == ["ok1", "ok2"]
    assert sink.dropped == 1 and sink.written == 2


async def test_dbsink_drops_oldest_when_full() -> None:
    sink = DbSink(write=FakeDb(), max_buffer=2)
    for ev in ("a", "b", "c"):
        sink.emit(_trace(ev))
    assert sink.pending == 2 and sink.dropped == 1


async def test_dbsink_background_writer_and_stop_flushes() -> None:
    db = FakeDb()
    sink = DbSink(write=db, flush_interval_s=0.01)
    sink.start()
    sink.emit(_trace("first"))
    await asyncio.sleep(0.05)
    assert [t.event for t in db.rows] == ["first"]
    sink.emit(_trace("last"))
    await sink.stop()
    assert [t.event for t in db.rows] == ["first", "last"]


# ---- llm-gateway emits spans ------------------------------------------------------------------


def _gw(handler: httpx.MockTransport) -> Gateway:
    async def no_sleep(_s: float) -> None:
        return None

    s = Settings(_env_file=None, groq_api_key="gsk-test", voyage_api_key="pa-test")  # type: ignore[call-arg]
    return Gateway(s, transport=handler, sleep=no_sleep)


async def test_gateway_complete_writes_usage_to_trace(trace_sink: MemorySink) -> None:
    from pydantic import BaseModel

    class Out(BaseModel):
        ok: bool

    transport = httpx.MockTransport(
        lambda _r: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
            },
        )
    )
    bid = uuid4()
    with span("editor", "judge_claim", bid):
        await _gw(transport).complete("judge", [{"role": "user", "content": "x"}], Out)

    llm_t, editor_t = trace_sink.traces
    assert (llm_t.component, llm_t.event) == ("llm-gateway", "complete.judge")
    assert llm_t.parent_id == editor_t.id and llm_t.briefing_id == bid
    assert (llm_t.tokens_in, llm_t.tokens_out) == (1000, 100)
    assert llm_t.cost_usd == pytest.approx((1000 * 0.15 + 100 * 0.60) / 1e6)
    assert llm_t.payload == {"schema": "Out", "model": "openai/gpt-oss-120b", "attempts": 1}
    assert "x" not in str(llm_t.payload.values())  # prompts are not copied into traces


async def test_gateway_failure_is_traced(trace_sink: MemorySink) -> None:
    from pydantic import BaseModel

    class Out(BaseModel):
        ok: bool

    transport = httpx.MockTransport(lambda _r: httpx.Response(401, json={"error": {}}))
    with pytest.raises(LLMProviderError):
        await _gw(transport).complete("draft", [{"role": "user", "content": "x"}], Out)
    (t,) = trace_sink.traces
    assert t.error is not None and t.error.startswith("LLMProviderError: HTTP 401")
