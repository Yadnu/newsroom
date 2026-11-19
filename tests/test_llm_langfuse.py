"""Langfuse export from the gateway (task 3.2, decision 0005). No network: MockTransport only."""

import base64
import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.archive import MemorySink, span
from app.config import Settings
from app.db.models import EMBEDDING_DIM
from app.shared.llm import Gateway, LLMProviderError, Message
from app.shared.llm.langfuse import MAX_FIELD_CHARS, Langfuse

MSGS: list[Message] = [
    {"role": "system", "content": "You judge claims."},
    {"role": "user", "content": "Is it supported?"},
]


class Out(BaseModel):
    ok: bool


def _settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {
        "groq_api_key": "gsk-test",
        "voyage_api_key": "pa-test",
        "langfuse_public_key": "pk-lf-test",
        "langfuse_secret_key": "sk-lf-test",
        "langfuse_host": "https://lf.test/",
    }
    return Settings(_env_file=None, **(base | kw))  # type: ignore[call-arg]


async def _no_sleep(_s: float) -> None:
    return None


def _chat(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        },
    )


def _provider(req: httpx.Request) -> httpx.Response:
    body = json.loads(req.content)
    if req.url.path.endswith("/embeddings"):
        data = [{"index": i, "embedding": [0.1] * EMBEDDING_DIM} for i in range(len(body["input"]))]
        return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 7}})
    return _chat('{"ok": true}')


class LangfuseServer:
    def __init__(self, status: int = 207, fail: bool = False) -> None:
        self.status, self.fail = status, fail
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self.fail:
            raise httpx.ConnectError("down")
        return httpx.Response(self.status, json={"successes": [], "errors": []})

    def events(self) -> list[dict[str, Any]]:
        return [e for r in self.requests for e in json.loads(r.content)["batch"]]

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e["body"] for e in self.events() if e["type"] == kind]


def _gw(server: LangfuseServer, provider: Any = _provider, **kw: Any) -> tuple[Gateway, Langfuse]:
    settings = _settings(**kw)
    lf = Langfuse(settings, transport=httpx.MockTransport(server), sleep=_no_sleep)
    gw = Gateway(settings, transport=httpx.MockTransport(provider), sleep=_no_sleep, langfuse=lf)
    return gw, lf


async def test_disabled_without_keys_sends_nothing() -> None:
    server = LangfuseServer()
    gw, lf = _gw(server, langfuse_public_key=None, langfuse_secret_key="")
    assert not lf.enabled
    await gw.complete("judge", MSGS, Out)
    await gw.aclose()
    assert server.requests == []


async def test_default_gateway_without_keys_is_disabled() -> None:
    gw = Gateway(Settings(_env_file=None, groq_api_key="g", voyage_api_key="v"))  # type: ignore[call-arg]
    assert not gw.langfuse.enabled
    await gw.aclose()


async def test_complete_exports_trace_and_generation(trace_sink: MemorySink) -> None:
    server = LangfuseServer()
    gw, _ = _gw(server)
    with span("editor", "judge_claim", briefing_id=None) as outer:
        result, usage = await gw.complete("judge", MSGS, Out)
    await gw.aclose()
    assert result.ok

    (req,) = server.requests
    assert str(req.url) == "https://lf.test/api/public/ingestion"
    auth = base64.b64decode(req.headers["authorization"].removeprefix("Basic ")).decode()
    assert auth == "pk-lf-test:sk-lf-test"

    (call,) = [t for t in trace_sink.traces if t.event == "complete.judge"]
    (trace,) = server.of("trace-create")
    assert trace["id"] == str(call.id) and trace["name"] == "complete.judge"
    assert trace["metadata"]["parent_span_id"] == str(outer.id)
    assert trace["metadata"]["task"] == "judge" and trace["metadata"]["schema"] == "Out"

    (gen,) = server.of("generation-create")
    assert gen["traceId"] == str(call.id) and gen["model"] == usage.model
    assert gen["input"] == MSGS and gen["output"] == {"ok": True}
    assert gen["usageDetails"] == {"input": 100, "output": 20}
    assert gen["costDetails"]["total"] == pytest.approx(usage.cost_usd)
    assert gen["level"] == "DEFAULT" and gen["statusMessage"] is None
    assert gen["startTime"].endswith("Z") and gen["startTime"] <= gen["endTime"]


async def test_briefing_id_becomes_session_id() -> None:
    from uuid import uuid4

    server = LangfuseServer()
    gw, _ = _gw(server)
    bid = uuid4()
    with span("producer", "brief", briefing_id=bid):
        await gw.complete("draft", MSGS, Out)
    await gw.aclose()
    assert server.of("trace-create")[0]["sessionId"] == str(bid)


async def test_fallback_records_both_models_with_error_level() -> None:
    replies = iter([_chat("nope"), _chat("still nope"), _chat('{"ok": true}')])
    server = LangfuseServer()
    gw, _ = _gw(server, provider=lambda r: next(replies))
    await gw.complete("draft", MSGS, Out)
    await gw.aclose()
    first, second = server.of("generation-create")
    assert first["model"] == "openai/gpt-oss-20b" and first["level"] == "ERROR"
    assert first["statusMessage"].startswith("StructuredOutputError")
    assert first["output"] == "still nope"  # the last invalid output, for prompt debugging
    assert second["model"] == "openai/gpt-oss-120b" and second["level"] == "DEFAULT"
    assert len(server.of("trace-create")) == 1  # one trace per gateway call


async def test_provider_failure_is_exported_then_raised() -> None:
    server = LangfuseServer()
    gw, _ = _gw(server, provider=lambda r: httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(LLMProviderError):
        await gw.complete("judge", MSGS, Out)
    await gw.aclose()
    (gen,) = server.of("generation-create")
    assert gen["level"] == "ERROR" and gen["output"] is None
    assert "gsk-test" not in json.dumps(server.events())  # provider key never exported


async def test_capture_content_off_sends_usage_only() -> None:
    server = LangfuseServer()
    gw, _ = _gw(server, langfuse_capture_content=False)
    await gw.complete("judge", MSGS, Out)
    await gw.aclose()
    (gen,) = server.of("generation-create")
    assert gen["input"] is None and gen["output"] is None
    assert gen["usageDetails"] == {"input": 100, "output": 20}


async def test_embed_exports_counts_not_texts() -> None:
    server = LangfuseServer()
    gw, _ = _gw(server)
    await gw.embed(["secret-ish article text", "another"], "query")
    await gw.embed([])  # no call, no export
    await gw.aclose()
    (gen,) = server.of("generation-create")
    assert gen["name"] == "embed" and gen["model"] == "voyage-4-lite"
    assert gen["input"] == {"n_texts": 2, "input_type": "query"}
    assert gen["usageDetails"] == {"input": 7, "output": 0}
    assert "article text" not in json.dumps(server.events())


async def test_long_messages_are_clipped() -> None:
    server = LangfuseServer()
    gw, _ = _gw(server)
    big: list[Message] = [{"role": "user", "content": "x" * (MAX_FIELD_CHARS + 50)}]
    await gw.complete("judge", big, Out)
    await gw.aclose()
    (gen,) = server.of("generation-create")
    assert gen["input"][0]["content"].endswith("[truncated]")
    assert len(gen["input"][0]["content"]) < MAX_FIELD_CHARS + 20


@pytest.mark.parametrize("server", [LangfuseServer(status=500), LangfuseServer(fail=True)])
async def test_langfuse_outage_never_fails_the_call(server: LangfuseServer) -> None:
    gw, _ = _gw(server)
    result, _ = await gw.complete("judge", MSGS, Out)
    await gw.aclose()
    assert result.ok and len(server.requests) == 1


async def test_background_flush_sends_without_close() -> None:
    server = LangfuseServer()
    gw, lf = _gw(server)
    await gw.complete("judge", MSGS, Out)
    assert lf._task is not None
    await lf._task  # flush_interval elapses (no-op sleep), then the batch is sent
    assert len(server.of("generation-create")) == 1
    await gw.aclose()
    assert len(server.requests) == 1  # nothing left to send on close


async def test_batches_respect_batch_size() -> None:
    server = LangfuseServer()
    gw, _ = _gw(server, langfuse_batch_size=3)
    for _ in range(3):
        await gw.complete("judge", MSGS, Out)  # 2 events each
    await gw.aclose()
    sizes = [len(json.loads(r.content)["batch"]) for r in server.requests]
    assert sum(sizes) == 6 and max(sizes) <= 3
