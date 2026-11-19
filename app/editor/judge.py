"""``judge_claim()`` / ``judge_script()``: an LLM judge checks each claim against evidence.

The judge sees only the claim text and the retrieved evidence passages: never the Writer's line,
prompt, or other claims (decision 0002). The model answers the 5-check rubric; the verdict is
computed here from those answers (decision 0012):

- no evidence passages, ``supported`` failed, or no passage cited -> ``rejected``
- sensitive claim with cited passages from fewer than 2 outlets -> ``corroborated`` fails
- any of ``faithful``, ``attributed``, ``fresh``, ``corroborated`` failed -> ``rewrite``
- otherwise ``approved``, and the cited passages are stored as ``claim_evidence``
"""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, update

from app.archive import span
from app.config import get_settings
from app.db.models import Briefing, BriefingStatus, Claim, ClaimEvidence, Verdict
from app.db.session import session_scope
from app.editor.retrieve import ClaimRef, Passage, retrieve_evidence
from app.shared import llm
from app.writer import DraftClaim, Script
from app.writer.prompts import escape_attr, escape_text, load_prompt, render

CHECKS = ("supported", "faithful", "attributed", "fresh", "corroborated")
MIN_OUTLETS_SENSITIVE = 2

_claims = Claim.__table__  # type: ignore[attr-defined]
_evidence = ClaimEvidence.__table__  # type: ignore[attr-defined]
_briefings = Briefing.__table__  # type: ignore[attr-defined]


def today() -> date:
    return datetime.now(UTC).date()


# ---- LLM output schema ----------------------------------------------------------------------


class Check(BaseModel):
    passed: bool
    note: str


class JudgeOut(BaseModel):
    supported: Check
    faithful: Check
    attributed: Check
    fresh: Check
    corroborated: Check
    sensitive: bool
    evidence: list[str]
    confidence: float
    reason: str


# ---- public result --------------------------------------------------------------------------


class EvidencePassage(BaseModel):
    source_id: UUID
    outlet: str
    passage: str
    score: float


class ClaimVerdict(BaseModel):
    claim_id: UUID
    verdict: Verdict
    score: float
    reason: str
    checks: dict[str, bool]
    sensitive: bool
    evidence: list[EvidencePassage]


class JudgedScript(BaseModel):
    briefing_id: UUID
    verdicts: list[ClaimVerdict]

    def count(self, verdict: Verdict) -> int:
        return sum(v.verdict == verdict for v in self.verdicts)


# ---- prompting --------------------------------------------------------------------------------


def evidence_block(passages: Sequence[Passage]) -> tuple[str, dict[str, Passage]]:
    refs: dict[str, Passage] = {}
    blocks = []
    for i, p in enumerate(passages, 1):
        ref = f"E{i}"
        refs[ref] = p
        published = p.published_at.date().isoformat() if p.published_at else "unknown"
        blocks.append(
            f'<evidence id="{ref}" outlet="{escape_attr(p.outlet)}" published="{published}">\n'
            f"{escape_text(p.text)}\n</evidence>"
        )
    return "\n\n".join(blocks), refs


def judge_messages(
    claim_text: str, passages: Sequence[Passage]
) -> tuple[list[llm.Message], dict[str, Passage]]:
    block, refs = evidence_block(passages)
    user = render(
        "editor/judge_user",
        today=today().isoformat(),
        claim=escape_text(claim_text),
        evidence=block,
    )
    return [
        {"role": "system", "content": load_prompt("editor/judge_system")},
        {"role": "user", "content": user},
    ], refs


# ---- verdict (pure) ---------------------------------------------------------------------------


def decide(claim_id: UUID, out: JudgeOut, refs: dict[str, Passage]) -> ClaimVerdict:
    cited = [refs[r] for r in dict.fromkeys(e.strip() for e in out.evidence) if r in refs]
    checks = {name: getattr(out, name).passed for name in CHECKS}
    notes = {name: getattr(out, name).note for name in CHECKS}
    outlets = {p.outlet.casefold() for p in cited}
    if out.sensitive:
        enough = len(outlets) >= MIN_OUTLETS_SENSITIVE
        if not enough:
            notes["corroborated"] = f"sensitive claim cited by {len(outlets)} outlet(s), needs 2"
        checks["corroborated"] = checks["corroborated"] and enough
    else:
        checks["corroborated"] = True  # corroboration is only required for sensitive claims

    failed = [name for name in CHECKS if not checks[name]]
    if not cited and checks["supported"]:
        failed.insert(0, "supported")
        checks["supported"] = False
        notes["supported"] = "no evidence passage was cited"
    if not checks["supported"]:
        verdict = Verdict.rejected
    elif failed:
        verdict = Verdict.rewrite
    else:
        verdict = Verdict.approved

    reason = out.reason.strip()
    if failed:
        reason = "; ".join(f"{name}: {notes[name].strip()}" for name in failed)
    evidence = [] if verdict == Verdict.rejected else cited
    return ClaimVerdict(
        claim_id=claim_id,
        verdict=verdict,
        score=min(max(out.confidence, 0.0), 1.0),
        reason=reason,
        checks=checks,
        sensitive=out.sensitive,
        evidence=[
            EvidencePassage(
                source_id=p.source_id, outlet=p.outlet, passage=p.text, score=p.similarity
            )
            for p in evidence
        ],
    )


def no_evidence(claim_id: UUID) -> ClaimVerdict:
    return ClaimVerdict(
        claim_id=claim_id,
        verdict=Verdict.rejected,
        score=0.0,
        reason="no evidence passages: every cited source is missing or retracted",
        checks=dict.fromkeys(CHECKS, False),
        sensitive=False,
        evidence=[],
    )


def judge_failed(claim_id: UUID, error: Exception) -> ClaimVerdict:
    """The judge call failed: the claim stays ``pending`` (never airs) and is not stored."""
    return ClaimVerdict(
        claim_id=claim_id,
        verdict=Verdict.pending,
        score=0.0,
        reason=f"judge failed: {type(error).__name__}",
        checks=dict.fromkeys(CHECKS, False),
        sensitive=False,
        evidence=[],
    )


# ---- judging --------------------------------------------------------------------------------


async def judge_passages(claim: ClaimRef, passages: Sequence[Passage]) -> ClaimVerdict:
    # The claim text and reason are recorded so rejections survive a rewrite (decision 0013).
    with span(
        "editor",
        "judge_claim",
        claim_id=claim.id,
        line_id=claim.line_id,
        claim=claim.text,
        passages=len(passages),
    ) as s:
        if not passages:
            v = no_evidence(claim.id)
        else:
            messages, refs = judge_messages(claim.text, passages)
            try:
                out = await llm.complete("judge", messages, JudgeOut)
            except llm.LLMError as e:
                v = judge_failed(claim.id, e)
            else:
                v = decide(claim.id, out, refs)
        s.set(
            verdict=v.verdict.value,
            score=v.score,
            reason=v.reason,
            checks=v.checks,
            sensitive=v.sensitive,
            evidence=len(v.evidence),
        )
    return v


async def judge_all(
    claims: Sequence[DraftClaim], line_ids: Mapping[UUID, UUID] | None = None
) -> list[ClaimVerdict]:
    """Retrieve evidence once for all claims and judge them concurrently. Does not store.
    ``line_ids`` (claim id -> script line id) is recorded on each judge span."""
    lines = line_ids or {}
    refs = [_ref(c, lines.get(c.id)) for c in claims]
    if not refs:
        return []
    passages = await retrieve_evidence(refs)
    limit = asyncio.Semaphore(get_settings().editor_max_concurrency)

    async def one(c: ClaimRef) -> ClaimVerdict:
        async with limit:
            return await judge_passages(c, passages[c.id])

    return list(await asyncio.gather(*(one(c) for c in refs)))


def _ref(claim: DraftClaim, line_id: UUID | None = None) -> ClaimRef:
    return ClaimRef(
        id=claim.id, text=claim.text, source_ids=list(claim.source_ids), line_id=line_id
    )


async def judge_claim(claim: DraftClaim) -> ClaimVerdict:
    """Retrieve evidence, judge one claim, and store the verdict and its evidence."""
    ref = _ref(claim)
    passages = await retrieve_evidence([ref])
    verdict = await judge_passages(ref, passages[ref.id])
    await store_verdicts([verdict])
    return verdict


async def judge_script(script: Script) -> JudgedScript:
    """Judge every claim in the script concurrently; mark the briefing ``judged``."""
    claims = [c for line in script.lines for c in line.claims]
    with span("editor", "judge_script", script.briefing_id, claims=len(claims)) as s:
        line_ids = {c.id: line.id for line in script.lines for c in line.claims}
        verdicts = await judge_all(claims, line_ids)
        await store_verdicts(verdicts, briefing_id=script.briefing_id)
        judged = JudgedScript(briefing_id=script.briefing_id, verdicts=verdicts)
        s.set(**{v.value: judged.count(v) for v in Verdict if v != Verdict.pending})
    return judged


async def store_verdicts(verdicts: Sequence[ClaimVerdict], briefing_id: UUID | None = None) -> None:
    """Write verdicts and evidence in one transaction. Re-judging replaces old evidence.
    ``pending`` verdicts (judge failed) are not written: the claim keeps its stored state."""
    verdicts = [v for v in verdicts if v.verdict != Verdict.pending]
    for v in verdicts:
        if v.verdict == Verdict.approved and not v.evidence:
            raise AssertionError(f"claim {v.claim_id}: approved without evidence")
    now = datetime.now(UTC)
    async with session_scope() as session:
        if verdicts:
            ids = [v.claim_id for v in verdicts]
            await session.exec(delete(_evidence).where(_evidence.c.claim_id.in_(ids)))
        for v in verdicts:
            await session.exec(
                update(_claims)
                .where(_claims.c.id == v.claim_id)
                .values(verdict=v.verdict.value, score=v.score, reason=v.reason, judged_at=now)
            )
        rows = [
            ClaimEvidence(
                claim_id=v.claim_id, source_id=e.source_id, passage=e.passage, score=e.score
            )
            for v in verdicts
            for e in v.evidence
        ]
        session.add_all(rows)
        await session.flush()
        if briefing_id is not None:
            await session.exec(
                update(_briefings)
                .where(_briefings.c.id == briefing_id)
                .values(status=BriefingStatus.judged.value)
            )
