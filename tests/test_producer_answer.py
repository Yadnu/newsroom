"""producer.answer_question() and handle_question() with the pipeline faked (task 5.3)."""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

import app.producer.answer as answer_mod
from app.archive import MemorySink
from app.caller import CallerQuestion
from app.config import Settings
from app.db.models import Verdict
from app.editor import ClaimVerdict, EvidencePassage, ReviewedScript
from app.producer.answer import SAFE_LINE, AnswerResult, answer_question, handle_question
from app.standards_desk import ClearedLine, ClearedScript, NotClearedError, ScreenResult
from app.standards_desk.types import _CLEARANCE
from app.writer import DraftClaim, DraftLine
from app.writer.draft import CleanClaim, CleanLine, SourceText

STORY = uuid4()
SCRIPT = ClearedScript._issue(
    _CLEARANCE, uuid4(), (ClearedLine(uuid4(), STORY, 0, "Nvidia named a chief.", (uuid4(),)),), ()
)
SRC = SourceText(uuid4(), "Wired", "Nvidia", "Kress leads Nvidia.", None)


def question(**kw: Any) -> CallerQuestion:
    base: dict[str, Any] = {
        "transcript": "who runs nvidia now",
        "intent": "follow_up",
        "story_id": STORY,
        "restated": "Who runs Nvidia now?",
        "screen": ScreenResult(True, "ok", "", "llm"),
    }
    return CallerQuestion(**(base | kw))


def settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


class Fakes:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sources: list[SourceText] = [SRC]
        self.drafted: list[CleanLine] = [
            CleanLine(
                "Colette Kress is Nvidia's interim chief.", [CleanClaim("Kress leads.", [SRC.id])]
            )
        ]
        self.verdict = Verdict.approved
        self.clear_raises = False
        self.draft_delay = 0.0
        self.stored: list[tuple[str, list[str]]] = []
        self.cleared_with: list[bool] = []
        self.asked: list[str] = []
        monkeypatch.setattr(answer_mod, "answer_sources", self.answer_sources)
        monkeypatch.setattr(answer_mod, "draft_answer", self.draft_answer)
        monkeypatch.setattr(answer_mod, "store_answer", self.store_answer)
        monkeypatch.setattr(answer_mod.judge, "judge_all", self.judge_all)
        monkeypatch.setattr(answer_mod.judge, "store_verdicts", self.store_verdicts)
        monkeypatch.setattr(answer_mod, "clear_for_air", self.clear_for_air)

    async def answer_sources(self, q: CallerQuestion, s: ClearedScript, n: int) -> Any:
        return q.story_id or STORY, "Nvidia story", self.sources

    async def draft_answer(
        self, asked: str, title: str, sources: Any, **kw: Any
    ) -> list[CleanLine]:
        self.asked.append(asked)
        await asyncio.sleep(self.draft_delay)
        return self.drafted

    async def store_answer(
        self, briefing_id: UUID, story_id: UUID, q: str, lines: Any
    ) -> list[DraftLine]:
        self.stored.append((q, [ln.text for ln in lines]))
        return [
            DraftLine(
                id=uuid4(),
                story_id=story_id,
                order=1000 + i,
                text=ln.text,
                claims=[
                    DraftClaim(id=uuid4(), text=c.text, source_ids=c.source_ids) for c in ln.claims
                ],
            )
            for i, ln in enumerate(lines)
        ]

    async def judge_all(self, claims: Any, line_ids: Any = None) -> list[ClaimVerdict]:
        ev = [EvidencePassage(source_id=SRC.id, outlet="Wired", passage="p", score=0.8)]
        return [
            ClaimVerdict(
                claim_id=c.id,
                verdict=self.verdict,
                score=0.9,
                reason="ok",
                checks={},
                sensitive=False,
                evidence=ev if self.verdict == Verdict.approved else [],
            )
            for c in claims
        ]

    async def store_verdicts(self, verdicts: Any, briefing_id: Any = None) -> None:
        assert briefing_id is None  # an answer never touches the briefing status

    async def clear_for_air(self, reviewed: ReviewedScript, *, mark_briefing: bool = True) -> Any:
        self.cleared_with.append(mark_briefing)
        lines = reviewed.script.lines
        approved = self.verdict == Verdict.approved
        keep = [ln for ln in lines if not ln.claims or approved]
        if self.clear_raises or not keep:
            raise NotClearedError("all blocked")
        return ClearedScript._issue(
            _CLEARANCE,
            reviewed.script.briefing_id,
            tuple(ClearedLine(ln.id, ln.story_id, ln.order, ln.text, ()) for ln in keep),
            (),
        )


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Fakes:
    return Fakes(monkeypatch)


async def test_happy_path_returns_cleared_answer(fakes: Fakes, trace_sink: MemorySink) -> None:
    result = await answer_question(question(), SCRIPT, settings=settings())
    assert not result.fallback
    assert [ln.text for ln in result.cleared.lines] == ["Colette Kress is Nvidia's interim chief."]
    assert fakes.asked == ["Who runs Nvidia now?"]  # the restated question
    assert fakes.stored == [("who runs nvidia now", ["Colette Kress is Nvidia's interim chief."])]
    assert fakes.cleared_with == [False]  # briefing status untouched
    span = next(t for t in trace_sink.traces if t.event == "answer")
    for key in ("sources_ms", "draft_ms", "judge_ms", "clear_ms", "total_ms"):
        assert key in span.payload
    assert span.payload["fallback"] is False and span.payload["approved"] == 1


@pytest.mark.parametrize("case", ["rejected", "no_sources", "timeout"])
async def test_failures_fall_back_to_the_safe_line(fakes: Fakes, case: str) -> None:
    kw: dict[str, Any] = {}
    if case == "rejected":
        fakes.verdict = Verdict.rejected
    elif case == "no_sources":
        fakes.sources = []
    else:
        fakes.draft_delay = 0.5
        kw["producer_answer_timeout_s"] = 0.1
    result = await answer_question(question(), SCRIPT, settings=settings(**kw))
    assert result.fallback
    assert [ln.text for ln in result.cleared.lines] == [SAFE_LINE]
    assert fakes.stored[-1] == ("who runs nvidia now", [SAFE_LINE])


class FakeSession:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.resumed = 0
        self.interjected: list[tuple[Any, str]] = []

    async def send_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def resume(self) -> None:
        self.resumed += 1

    def interject(self, script: Any, question_id: str) -> None:
        self.interjected.append((script, question_id))


async def test_handle_question_answers_then_resumes() -> None:
    q = question()
    answer = ClearedScript._issue(
        _CLEARANCE, SCRIPT.briefing_id, (ClearedLine(uuid4(), STORY, 1000, "Kress leads.", ()),), ()
    )

    async def answerer(qq: CallerQuestion, s: ClearedScript) -> AnswerResult:
        return AnswerResult(answer, False, 3200)

    session = FakeSession()
    await handle_question(q, SCRIPT, session, answerer=answerer)
    states = [e["state"] for e in session.events]
    assert states == ["thinking", "answering"]
    assert session.events[1]["lines"][0]["text"] == "Kress leads."
    assert session.interjected == [(answer, str(q.id))] and session.resumed == 1


@pytest.mark.parametrize(
    "q",
    [
        question(screen=ScreenResult(False, "injection", "nope", "rules")),
        question(intent="off_topic"),
        question(intent="unknown"),
    ],
)
async def test_handle_question_declines_without_answering(q: CallerQuestion) -> None:
    async def answerer(qq: CallerQuestion, s: ClearedScript) -> AnswerResult:
        raise AssertionError("must not answer")

    session = FakeSession()
    await handle_question(q, SCRIPT, session, answerer=answerer)
    assert [e["state"] for e in session.events] == ["declined"]
    assert session.interjected == [] and session.resumed == 1


async def test_handle_question_failure_still_resumes() -> None:
    async def answerer(qq: CallerQuestion, s: ClearedScript) -> AnswerResult:
        raise RuntimeError("db down")

    session = FakeSession()
    await handle_question(question(), SCRIPT, session, answerer=answerer)
    assert [e["state"] for e in session.events] == ["thinking", "failed"]
    assert session.resumed == 1
