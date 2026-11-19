"""``review_script()``: judge, send failed lines back to the Writer, re-judge. Max N rounds.

Round 0 is ``judge_script()``. Each later round takes every line with a claim that is not
``approved``, asks ``writer.rewrite_line()`` for a new version with the Editor's reasons, and
judges only the new claims. It stops when every claim is approved or after
``rewrite_max_rounds`` (2) rounds. A rewrite that fails (``WriterError``) keeps the old line and
verdicts. Lines still not approved after the last round stay as they are; the Standards Desk
keeps them off the air (decision 0013).
"""

import asyncio
from uuid import UUID

from pydantic import BaseModel

from app.archive import span
from app.config import get_settings
from app.db.models import Verdict
from app.editor import judge
from app.editor.judge import ClaimVerdict
from app.log import get_logger
from app.shared import llm
from app.writer import (
    ClaimFeedback,
    DraftClaim,
    DraftLine,
    Script,
    WriterError,
    rewrite_line,
)

log = get_logger(__name__)


class ReviewedScript(BaseModel):
    script: Script
    verdicts: list[ClaimVerdict]  # in script order, one per current claim
    rounds: int  # rewrite rounds actually run

    def count(self, verdict: Verdict) -> int:
        return sum(v.verdict == verdict for v in self.verdicts)


# A pending verdict means the judge call failed: not the Writer's fault, so no rewrite.
SEND_BACK = frozenset({Verdict.rewrite, Verdict.rejected})


def needs_rewrite(line: DraftLine, verdicts: dict[UUID, ClaimVerdict]) -> bool:
    return any(verdicts[c.id].verdict in SEND_BACK for c in line.claims)


def feedback_for(line: DraftLine, verdicts: dict[UUID, ClaimVerdict]) -> list[ClaimFeedback]:
    return [
        ClaimFeedback(
            text=c.text, verdict=verdicts[c.id].verdict.value, reason=verdicts[c.id].reason
        )
        for c in line.claims
        if verdicts[c.id].verdict in SEND_BACK
    ]


async def _try_rewrite(
    line: DraftLine, feedback: list[ClaimFeedback], round_no: int
) -> DraftLine | None:
    try:
        return await rewrite_line(line, feedback, round_no)
    except (WriterError, llm.LLMError) as e:
        log.warning("editor.rewrite_failed", line_id=str(line.id), round=round_no, error=str(e))
        return None


async def review_script(script: Script) -> ReviewedScript:
    max_rounds = get_settings().rewrite_max_rounds
    with span("editor", "review_script", script.briefing_id, max_rounds=max_rounds) as s:
        judged = await judge.judge_script(script)
        verdicts: dict[UUID, ClaimVerdict] = {v.claim_id: v for v in judged.verdicts}
        lines = list(script.lines)
        rounds = 0
        for round_no in range(1, max_rounds + 1):
            todo = [i for i, line in enumerate(lines) if needs_rewrite(line, verdicts)]
            if not todo:
                break
            rounds = round_no
            with span("editor", "rewrite_round", round=round_no, lines=len(todo)) as rs:
                results = await asyncio.gather(
                    *(
                        _try_rewrite(lines[i], feedback_for(lines[i], verdicts), round_no)
                        for i in todo
                    )
                )
                new_claims: list[DraftClaim] = []
                line_ids: dict[UUID, UUID] = {}
                for i, new in zip(todo, results, strict=True):
                    if new is None:
                        continue
                    for c in lines[i].claims:
                        verdicts.pop(c.id)
                    lines[i] = new
                    new_claims.extend(new.claims)
                    line_ids.update({c.id: new.id for c in new.claims})
                fresh = await judge.judge_all(new_claims, line_ids)
                await judge.store_verdicts(fresh)
                verdicts.update({v.claim_id: v for v in fresh})
                rs.set(
                    rewritten=sum(r is not None for r in results),
                    failed=sum(r is None for r in results),
                    approved=sum(v.verdict == Verdict.approved for v in fresh),
                )

        final = Script(briefing_id=script.briefing_id, lines=lines)
        reviewed = ReviewedScript(
            script=final,
            verdicts=[verdicts[c.id] for line in lines for c in line.claims],
            rounds=rounds,
        )
        s.set(
            rounds=rounds, **{v.value: reviewed.count(v) for v in Verdict if v != Verdict.pending}
        )
    return reviewed
