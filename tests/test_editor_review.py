from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID, uuid4

import pytest

import app.editor.judge as judge
import app.editor.review as review
from app.archive import MemorySink
from app.config import get_settings
from app.db.models import Verdict
from app.editor import ClaimVerdict, EvidencePassage, review_script
from app.writer import ClaimFeedback, DraftClaim, DraftLine, Script, WriterError


def verdict_for(claim: DraftClaim, verdict: Verdict) -> ClaimVerdict:
    approved = verdict == Verdict.approved
    return ClaimVerdict(
        claim_id=claim.id,
        verdict=verdict,
        score=0.9 if approved else 0.4,
        reason="ok" if approved else f"attributed: say who said {claim.text!r}",
        checks={},
        sensitive=False,
        evidence=[EvidencePassage(source_id=uuid4(), outlet="A", passage="p", score=0.8)]
        if approved
        else [],
    )


class Harness:
    """Fake judge (verdict by claim text) and fake Writer (scripted rewrites)."""

    def __init__(self, rule: Callable[[str], Verdict]) -> None:
        self.rule = rule
        self.judged: list[list[str]] = []  # claim texts per judge_all call
        self.stored: list[tuple[list[ClaimVerdict], UUID | None]] = []
        self.rewrites: list[tuple[str, list[ClaimFeedback], int]] = []
        self.rewrite_text: Callable[[str, int], str | None] = lambda t, r: f"Acme says {t}"

    async def judge_all(self, claims: Sequence[DraftClaim]) -> list[ClaimVerdict]:
        self.judged.append([c.text for c in claims])
        return [verdict_for(c, self.rule(c.text)) for c in claims]

    async def store(
        self, verdicts: Sequence[ClaimVerdict], briefing_id: UUID | None = None
    ) -> None:
        self.stored.append((list(verdicts), briefing_id))

    async def rewrite_line(
        self, line: DraftLine, feedback: Sequence[ClaimFeedback], round_no: int
    ) -> DraftLine:
        self.rewrites.append((line.text, list(feedback), round_no))
        text = self.rewrite_text(line.text, round_no)
        if text is None:
            raise WriterError("still invalid")
        return DraftLine(
            id=line.id,
            story_id=line.story_id,
            order=line.order,
            text=text,
            claims=[DraftClaim(id=uuid4(), text=text, source_ids=[uuid4()])],
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable[[str], Verdict]], Harness]:
    def install(rule: Callable[[str], Verdict]) -> Harness:
        h = Harness(rule)
        monkeypatch.setattr(judge, "judge_all", h.judge_all)
        monkeypatch.setattr(judge, "store_verdicts", h.store)
        monkeypatch.setattr(review, "rewrite_line", h.rewrite_line)
        return h

    return install


def _line(order: int, *claims: str) -> DraftLine:
    return DraftLine(
        id=uuid4(),
        story_id=uuid4(),
        order=order,
        text=" ".join(claims) or "Now to the markets.",
        claims=[DraftClaim(id=uuid4(), text=t, source_ids=[uuid4()]) for t in claims],
    )


def attributed_ok(text: str) -> Verdict:
    return Verdict.approved if text.startswith(("Acme says", "Fine")) else Verdict.rewrite


async def test_all_approved_needs_no_rewrite(harness: Any) -> None:
    h = harness(attributed_ok)
    script = Script(briefing_id=uuid4(), lines=[_line(0, "Fine fact."), _line(1)])
    out = await review_script(script)
    assert out.rounds == 0 and h.rewrites == []
    assert out.script == script and out.count(Verdict.approved) == 1
    assert [b for _, b in h.stored] == [script.briefing_id]  # judge_script marks the briefing


async def test_failed_line_is_rewritten_with_reasons_and_rejudged(
    harness: Any, trace_sink: MemorySink
) -> None:
    h = harness(attributed_ok)
    good, bad = _line(0, "Fine fact."), _line(1, "it ships Nova.")
    script = Script(briefing_id=uuid4(), lines=[good, bad])
    out = await review_script(script)

    assert out.rounds == 1
    ((old_text, feedback, round_no),) = h.rewrites
    assert old_text == "it ships Nova." and round_no == 1
    assert feedback == [
        ClaimFeedback(
            text="it ships Nova.",
            verdict="rewrite",
            reason="attributed: say who said 'it ships Nova.'",
        )
    ]
    assert h.judged[1] == ["Acme says it ships Nova."]  # only the new claims are re-judged
    assert out.script.lines[0] == good
    assert (
        out.script.lines[1].text == "Acme says it ships Nova." and out.script.lines[1].id == bad.id
    )
    assert [v.verdict for v in out.verdicts] == [Verdict.approved, Verdict.approved]
    assert {v.claim_id for v in out.verdicts} == {
        c.id for ln in out.script.lines for c in ln.claims
    }

    outer = next(t for t in trace_sink.traces if t.event == "review_script")
    rnd = next(t for t in trace_sink.traces if t.event == "rewrite_round")
    assert outer.payload["rounds"] == 1 and outer.payload["approved"] == 2
    assert rnd.parent_id == outer.id and rnd.payload["rewritten"] == 1


async def test_stops_after_max_rounds(harness: Any) -> None:
    h = harness(lambda text: Verdict.rejected)  # nothing ever passes
    h.rewrite_text = lambda t, r: f"Try {r}: {t}"
    script = Script(briefing_id=uuid4(), lines=[_line(0, "Bad fact.")])
    out = await review_script(script)

    assert get_settings().rewrite_max_rounds == 2
    assert out.rounds == 2 and [r for _, _, r in h.rewrites] == [1, 2]
    assert out.script.lines[0].text == "Try 2: Try 1: Bad fact."
    assert [v.verdict for v in out.verdicts] == [Verdict.rejected]
    assert len(h.judged) == 3  # initial + one per round


async def test_failed_rewrite_keeps_old_line_and_verdicts(harness: Any) -> None:
    h = harness(attributed_ok)
    h.rewrite_text = lambda t, r: None if r == 1 else f"Acme says {t}"
    bad = _line(0, "it ships Nova.")
    out = await review_script(Script(briefing_id=uuid4(), lines=[bad]))

    assert [r for _, _, r in h.rewrites] == [1, 2]  # round 2 retries the unchanged line
    assert h.rewrites[1][0] == "it ships Nova."
    assert out.rounds == 2 and out.verdicts[0].verdict == Verdict.approved


async def test_zero_rounds_only_judges(harness: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rewrite_max_rounds", 0)
    h = harness(lambda text: Verdict.rewrite)
    out = await review_script(Script(briefing_id=uuid4(), lines=[_line(0, "x.")]))
    assert out.rounds == 0 and h.rewrites == []
    assert out.verdicts[0].verdict == Verdict.rewrite
