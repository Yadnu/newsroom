import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

import app.shared.llm as llm
from app.config import Settings
from app.db.models import EMBEDDING_DIM
from app.shared.llm import (
    Gateway,
    LLMConfigError,
    LLMProviderError,
    Message,
    StructuredOutputError,
)
from app.shared.llm.gateway import cost_usd
from app.shared.llm.schema import strict_json_schema

MSGS: list[Message] = [{"role": "user", "content": "Is the claim supported?"}]


class Inner(BaseModel):
    url: str


class Verdict(BaseModel):
    approved: bool
    reason: str
    note: str | None = None
    evidence: list[Inner] = []


def _settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {"groq_api_key": "gsk-test", "voyage_api_key": "pa-test"}
    return Settings(_env_file=None, **(base | kw))  # type: ignore[call-arg]


def _chat(content: str, t_in: int = 100, t_out: int = 20) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": t_in, "completion_tokens": t_out},
        },
    )


class Recorder:
    """Mock transport that replays responses in order and records requests."""

    def __init__(self, *responses: httpx.Response | Callable[[httpx.Request], httpx.Response]):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        r = self.responses.pop(0)
        return r(request) if callable(r) else r

    def body(self, i: int = 0) -> dict[str, Any]:
        out: dict[str, Any] = json.loads(self.requests[i].content)
        return out


async def _no_sleep(_s: float) -> None:
    return None


def _gw(rec: Recorder, **kw: Any) -> Gateway:
    return Gateway(_settings(**kw), transport=httpx.MockTransport(rec), sleep=_no_sleep)


# ---- routing and config ----------------------------------------------------------------


async def test_complete_routes_by_task_and_parses_schema() -> None:
    ok = Verdict(approved=True, reason="matches source").model_dump_json()
    rec = Recorder(_chat(ok), _chat(ok))
    gw = _gw(rec)

    result, usage = await gw.complete("judge", MSGS, Verdict)
    await gw.complete("draft", MSGS, Verdict)

    assert result == Verdict(approved=True, reason="matches source")
    assert rec.body(0)["model"] == "openai/gpt-oss-120b"
    assert rec.body(1)["model"] == "openai/gpt-oss-20b"
    assert str(rec.requests[0].url) == "https://api.groq.com/openai/v1/chat/completions"
    assert rec.requests[0].headers["authorization"] == "Bearer gsk-test"
    assert usage.model == "openai/gpt-oss-120b"
    assert (usage.tokens_in, usage.tokens_out, usage.attempts) == (100, 20, 1)
    assert usage.cost_usd == pytest.approx((100 * 0.15 + 20 * 0.60) / 1e6)
    assert usage.latency_ms >= 0


async def test_route_override_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "NEWSROOM_LLM_ROUTES",
        json.dumps({"draft": "m-a", "judge": "m-b", "classify": "m-a", "answer": "m-a"}),
    )
    monkeypatch.setenv(
        "NEWSROOM_LLM_PRICES",
        json.dumps({"m-a": [1, 2], "m-b": [3, 4], "voyage-4-lite": [0.02, 0]}),
    )
    monkeypatch.setenv("NEWSROOM_LLM_FALLBACKS", json.dumps({"draft": "m-b"}))
    gw = _gw(Recorder())
    assert gw.model_for("judge") == "m-b"
    assert gw.fallback_for("draft") == "m-b" and gw.fallback_for("judge") is None


def test_missing_route_or_price_fails_fast() -> None:
    with pytest.raises(LLMConfigError, match="tasks"):
        _gw(Recorder(), llm_routes={"draft": "openai/gpt-oss-20b"})
    with pytest.raises(LLMConfigError, match="price"):
        _gw(
            Recorder(),
            llm_routes=dict.fromkeys(("draft", "judge", "classify", "answer"), "unpriced"),
        )


async def test_missing_api_key_raises() -> None:
    gw = Gateway(_settings(groq_api_key=None), transport=httpx.MockTransport(Recorder()))
    with pytest.raises(LLMConfigError, match="NEWSROOM_GROQ_API_KEY"):
        await gw.complete("judge", MSGS, Verdict)


def test_cost_usd() -> None:
    assert cost_usd({"m": (1.0, 2.0)}, "m", 1_000_000, 500_000) == pytest.approx(2.0)
    with pytest.raises(LLMConfigError):
        cost_usd({}, "m", 1, 1)


# ---- structured output -----------------------------------------------------------------


def test_strict_schema_requires_all_fields_and_forbids_extras() -> None:
    s = strict_json_schema(Verdict)
    assert set(s["required"]) == {"approved", "reason", "note", "evidence"}
    assert s["additionalProperties"] is False
    inner = s["$defs"]["Inner"]
    assert inner["required"] == ["url"] and inner["additionalProperties"] is False
    assert "default" not in json.dumps(s)


async def test_request_sends_strict_json_schema() -> None:
    rec = Recorder(_chat(Verdict(approved=False, reason="x").model_dump_json()))
    await _gw(rec).complete("judge", MSGS, Verdict)
    rf = rec.body()["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "Verdict"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == strict_json_schema(Verdict)
    assert rec.body()["messages"] == MSGS


async def test_invalid_output_is_resampled_once_and_tokens_summed() -> None:
    good = Verdict(approved=True, reason="ok").model_dump_json()
    rec = Recorder(_chat('{"approved": "maybe"}', 10, 5), _chat(good, 10, 5))
    result, usage = await _gw(rec).complete("judge", MSGS, Verdict)
    assert result.approved is True
    assert (usage.tokens_in, usage.tokens_out, usage.attempts) == (20, 10, 2)


async def test_groq_json_validate_failed_is_resampled() -> None:
    bad = httpx.Response(
        400, json={"error": {"code": "json_validate_failed", "message": "schema mismatch"}}
    )
    rec = Recorder(bad, _chat(Verdict(approved=True, reason="ok").model_dump_json()))
    result, _ = await _gw(rec).complete("judge", MSGS, Verdict)
    assert result.reason == "ok"


async def test_persistently_invalid_output_raises() -> None:
    rec = Recorder(_chat("not json"), _chat("{}"))
    with pytest.raises(StructuredOutputError):
        await _gw(rec).complete("judge", MSGS, Verdict)


# ---- retries -----------------------------------------------------------------------------


async def test_retries_429_then_succeeds_and_honors_retry_after() -> None:
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)

    ok = Verdict(approved=True, reason="ok").model_dump_json()
    rec = Recorder(
        httpx.Response(429, headers={"retry-after": "2"}, json={"error": {"message": "rate"}}),
        httpx.Response(503),
        _chat(ok),
    )
    gw = Gateway(_settings(), transport=httpx.MockTransport(rec), sleep=sleep)
    _, usage = await gw.complete("judge", MSGS, Verdict)
    assert usage.attempts == 3
    assert slept == [2.0, 1.0]


async def test_gives_up_after_max_attempts() -> None:
    rec = Recorder(*[httpx.Response(500) for _ in range(3)])
    with pytest.raises(LLMProviderError) as exc:
        await _gw(rec, llm_max_attempts=3).complete("judge", MSGS, Verdict)
    assert exc.value.status_code == 500
    assert len(rec.requests) == 3


async def test_transport_error_is_retried() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=req)

    rec = Recorder(boom, _chat(Verdict(approved=True, reason="ok").model_dump_json()))
    _, usage = await _gw(rec).complete("judge", MSGS, Verdict)
    assert usage.attempts == 2


async def test_non_retryable_error_does_not_retry_or_leak_key() -> None:
    rec = Recorder(httpx.Response(401, json={"error": {"message": "invalid api key"}}))
    with pytest.raises(LLMProviderError) as exc:
        await _gw(rec).complete("judge", MSGS, Verdict)
    assert len(rec.requests) == 1
    assert "gsk-test" not in str(exc.value)


# ---- embeddings ----------------------------------------------------------------------------


def _embed_response(req: httpx.Request) -> httpx.Response:
    texts = json.loads(req.content)["input"]
    data = [{"index": i, "embedding": [float(i)] * EMBEDDING_DIM} for i in range(len(texts))]
    return httpx.Response(
        200, json={"data": list(reversed(data)), "usage": {"total_tokens": 3 * len(texts)}}
    )


async def test_embed_batches_orders_and_prices() -> None:
    rec = Recorder(_embed_response, _embed_response)
    texts = [f"t{i}" for i in range(1500)]
    vectors, usage = await _gw(rec).embed(texts, "query")

    assert len(vectors) == 1500 and all(len(v) == EMBEDDING_DIM for v in vectors)
    assert vectors[0][0] == 0.0 and vectors[999][0] == 999.0 and vectors[1000][0] == 0.0
    assert [len(rec.body(i)["input"]) for i in range(2)] == [1000, 500]
    body = rec.body(0)
    assert body["model"] == "voyage-4-lite"
    assert body["output_dimension"] == EMBEDDING_DIM
    assert body["input_type"] == "query"
    assert str(rec.requests[0].url) == "https://api.voyageai.com/v1/embeddings"
    assert usage.tokens_in == 4500
    assert usage.cost_usd == pytest.approx(4500 * 0.02 / 1e6)


async def test_embed_empty_makes_no_call() -> None:
    rec = Recorder()
    vectors, usage = await _gw(rec).embed([])
    assert vectors == [] and usage.cost_usd == 0.0 and not rec.requests


async def test_embed_rejects_wrong_dimension() -> None:
    rec = Recorder(httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 8}]}))
    with pytest.raises(LLMProviderError, match="dims"):
        await _gw(rec).embed(["x"])


# ---- module-level API ----------------------------------------------------------------------


async def test_module_functions_use_installed_gateway() -> None:
    rec = Recorder(_chat(Verdict(approved=True, reason="ok").model_dump_json()), _embed_response)
    llm.set_gateway(_gw(rec))
    try:
        assert (await llm.complete("classify", MSGS, Verdict)).approved is True
        assert len(await llm.embed(["a"])) == 1
    finally:
        await llm.aclose()
    assert llm._gateway is None


# ---- fallback (decision 0014) ----------------------------------------------------------------


async def test_invalid_output_falls_back_to_task_fallback_model(trace_sink: Any) -> None:
    good = Verdict(approved=True, reason="ok").model_dump_json()
    rec = Recorder(_chat("not json"), _chat("{}"), _chat(good, 50, 10))
    result, usage = await _gw(rec).complete("draft", MSGS, Verdict)
    assert result.reason == "ok"
    assert [rec.body(i)["model"] for i in range(3)] == [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
    ]
    assert usage.model == "openai/gpt-oss-120b"
    (s,) = [t for t in trace_sink.traces if t.event == "complete.draft"]
    assert s.payload["fallback_from"] == "openai/gpt-oss-20b"
    assert s.payload["model"] == "openai/gpt-oss-120b"


async def test_rate_limit_after_retries_falls_back() -> None:
    good = Verdict(approved=True, reason="ok").model_dump_json()
    rec = Recorder(httpx.Response(429), httpx.Response(429), _chat(good))
    result, _ = await _gw(rec, llm_max_attempts=2).complete("draft", MSGS, Verdict)
    assert result.approved is True and rec.body(2)["model"] == "openai/gpt-oss-120b"


async def test_auth_error_does_not_fall_back() -> None:
    rec = Recorder(httpx.Response(401, json={"error": {"message": "bad key"}}))
    with pytest.raises(LLMProviderError):
        await _gw(rec).complete("draft", MSGS, Verdict)
    assert len(rec.requests) == 1


async def test_judge_has_no_fallback() -> None:
    rec = Recorder(_chat("not json"), _chat("{}"))
    with pytest.raises(StructuredOutputError):
        await _gw(rec).complete("judge", MSGS, Verdict)
    assert len(rec.requests) == 2


def test_fallback_model_must_be_priced() -> None:
    with pytest.raises(LLMConfigError, match="no price"):
        _gw(Recorder(), llm_fallbacks={"draft": "unpriced-model"})
