"""``clear_for_air()``: the last gate before the Anchor (task 4.1, decision 0016).

Rules, checked per line in this order (the first failure blocks the line):
1. unapproved      every claim is stored as ``approved`` with evidence from a non-retracted source
2. unchecked_fact  a line without claims must be a short sign-post: no digits, quotes, names
                   or reported speech, at most ``standards_max_transition_words`` words
3. long_quote      quotes stay under 15 words (same rule the Writer validates)
4. verbatim        no run of ``standards_max_copied_words`` words copied from a cited source
5. opinion         no evaluative word in an unattributed sentence
Then a story whose every claim-bearing line was blocked loses its transitions too.

Claim status is read back from Postgres, not taken from the in-memory verdicts, so the
non-negotiable "no claim reaches the Anchor without approved + evidence" holds for what is stored.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text

from app.archive import span
from app.config import get_settings
from app.db.models import BriefingStatus, Verdict
from app.db.session import get_engine
from app.editor import ReviewedScript
from app.standards_desk.types import (
    _CLEARANCE,
    Block,
    BlockRule,
    ClearedLine,
    ClearedScript,
    NotClearedError,
)
from app.writer import DraftLine
from app.writer.draft import quote_violations

_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”")
_QUOTE_CHARS = re.compile(r"[\"“”]")
_APOSTROPHES = "'" + chr(0x2019)  # straight and curly
_WORD = re.compile("[a-z0-9]+(?:[" + _APOSTROPHES + "-][a-z0-9]+)*")
_POSSESSIVE = re.compile("[" + _APOSTROPHES + "]s[.,;:!?]*$", re.IGNORECASE)
_SENTENCE = re.compile(r"[^.!?]+[.!?]*")

# Evaluative words that state a judgement rather than a fact. Kept short on purpose (decision 0016).
OPINION_WORDS = frozenset(
    {
        "amazing",
        "awful",
        "best",
        "brilliant",
        "clearly",
        "disastrous",
        "fortunately",
        "greatest",
        "hopefully",
        "incredible",
        "obviously",
        "outrageous",
        "ridiculous",
        "sadly",
        "shocking",
        "should",
        "stunning",
        "terrible",
        "thankfully",
        "undoubtedly",
        "unfortunately",
        "worst",
    }
)
ATTRIBUTION_WORDS = frozenset(
    {
        "according",
        "added",
        "announced",
        "argued",
        "argues",
        "believe",
        "believes",
        "called",
        "calls",
        "claimed",
        "claims",
        "criticised",
        "criticized",
        "described",
        "noted",
        "notes",
        "praised",
        "reported",
        "reports",
        "said",
        "say",
        "says",
        "stated",
        "states",
        "suggested",
        "suggests",
        "told",
        "tells",
        "warn",
        "warned",
        "warns",
        "wrote",
        "writes",
    }
)


# ---- stored state ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredClaim:
    verdict: str
    evidence: int  # claim_evidence rows
    live_evidence: int  # ... whose source is not retracted


@dataclass(slots=True)
class StoredLines:
    claims: dict[UUID, dict[UUID, StoredClaim]] = field(default_factory=dict)  # line -> claims
    sources: dict[UUID, list[str]] = field(default_factory=dict)  # line -> cited/evidence texts


async def load_stored(line_ids: Sequence[UUID]) -> StoredLines:
    out = StoredLines()
    if not line_ids:
        return out
    async with get_engine().connect() as conn:
        for r in await conn.execute(
            text(
                "SELECT c.script_line_id, c.id, c.verdict,"
                " (SELECT count(*) FROM claim_evidence e WHERE e.claim_id = c.id) AS evidence,"
                " (SELECT count(*) FROM claim_evidence e JOIN sources s ON s.id = e.source_id"
                "   WHERE e.claim_id = c.id AND NOT s.retracted) AS live"
                " FROM claims c WHERE c.script_line_id = ANY(:ids)"
            ),
            {"ids": list(line_ids)},
        ):
            out.claims.setdefault(r.script_line_id, {})[r.id] = StoredClaim(
                r.verdict, r.evidence, r.live
            )
        for r in await conn.execute(
            text(
                "SELECT DISTINCT c.script_line_id, s.id, s.content FROM claims c"
                " JOIN (SELECT claim_id, source_id FROM claim_sources"
                "       UNION SELECT claim_id, source_id FROM claim_evidence) x"
                "   ON x.claim_id = c.id"
                " JOIN sources s ON s.id = x.source_id WHERE c.script_line_id = ANY(:ids)"
            ),
            {"ids": list(line_ids)},
        ):
            out.sources.setdefault(r.script_line_id, []).append(r.content)
    return out


async def set_status(briefing_id: UUID, status: BriefingStatus) -> None:
    async with get_engine().begin() as conn:
        await conn.execute(
            text("UPDATE briefings SET status = :s WHERE id = :b"),
            {"s": status.value, "b": briefing_id},
        )


# ---- rules (pure) ---------------------------------------------------------------------------


def words(text_: str) -> list[str]:
    return _WORD.findall(text_.lower())


def unquoted_segments(text_: str) -> list[str]:
    """The parts of a line outside quote marks (quoted words are allowed to match a source)."""
    return [seg for seg in _QUOTED.split(text_) if seg.strip()]


def copied_run(line_text: str, sources: Iterable[str], n: int) -> str | None:
    """The first run of ``n`` consecutive words outside quotes that also occurs in a source."""
    grams: set[tuple[str, ...]] = set()
    for src in sources:
        w = words(src)
        grams.update(tuple(w[i : i + n]) for i in range(len(w) - n + 1))
    if not grams:
        return None
    for seg in unquoted_segments(line_text):
        w = words(seg)
        for i in range(len(w) - n + 1):
            if tuple(w[i : i + n]) in grams:
                return " ".join(w[i : i + n])
    return None


def opinion_word(line_text: str) -> str | None:
    """An evaluative word outside quotes in a sentence with no attribution verb."""
    for sentence in _SENTENCE.findall(line_text):
        if ATTRIBUTION_WORDS.intersection(words(sentence)):
            continue
        for seg in unquoted_segments(sentence):
            hit = next((w for w in words(seg) if w in OPINION_WORDS), None)
            if hit:
                return hit
    return None


def transition_problem(line_text: str, max_words: int) -> str | None:
    """A line without claims is unchecked, so it may only be a short sign-post: no numbers,
    quotes, names (a capitalised word inside a sentence, or any possessive), or reported speech."""
    if any(ch.isdigit() for ch in line_text):
        return "a line without claims states a number"
    if _QUOTE_CHARS.search(line_text):
        return "a line without claims carries a quote"
    for sentence in _SENTENCE.findall(line_text):
        tokens = sentence.split()
        named = (
            t for i, t in enumerate(tokens) if (i > 0 and t[:1].isupper()) or _POSSESSIVE.search(t)
        )
        if name := next(named, None):
            return f"a line without claims names {name.strip('.,;:!?')!r}"
        if said := ATTRIBUTION_WORDS.intersection(words(sentence)):
            return f"a line without claims reports speech ({min(said)!r})"
    n = len(words(line_text))
    if n > max_words:
        return f"a line without claims has {n} words (transitions stay under {max_words + 1})"
    return None


def claim_problem(line: DraftLine, stored: dict[UUID, StoredClaim]) -> str | None:
    known = {c.id for c in line.claims}
    if extra := set(stored) - known:
        return f"{len(extra)} stored claim(s) on this line are not in the script"
    for c in line.claims:
        s = stored.get(c.id)
        label = c.text if len(c.text) <= 80 else c.text[:77] + "..."
        if s is None:
            return f"claim not stored: {label!r}"
        if s.verdict != Verdict.approved.value:
            return f"claim is {s.verdict}: {label!r}"
        if s.evidence == 0:
            return f"approved claim has no evidence: {label!r}"
        if s.live_evidence == 0:
            return f"all evidence comes from retracted sources: {label!r}"
    return None


def check_line(
    line: DraftLine, stored: StoredLines, max_copied: int, max_transition: int
) -> tuple[BlockRule, str] | None:
    if line.claims or line.id in stored.claims:
        if problem := claim_problem(line, stored.claims.get(line.id, {})):
            return BlockRule.unapproved, problem
    elif problem := transition_problem(line.text, max_transition):
        return BlockRule.unchecked_fact, problem
    if problems := quote_violations(line.text):
        return BlockRule.long_quote, problems[0]
    if run := copied_run(line.text, stored.sources.get(line.id, []), max_copied):
        return BlockRule.verbatim, f"copies {max_copied} words from a source: {run!r}"
    if hit := opinion_word(line.text):
        return BlockRule.opinion, f"evaluative word {hit!r} in an unattributed sentence"
    return None


def drop_orphaned_stories(lines: Sequence[DraftLine], blocks: dict[UUID, Block]) -> None:
    """Block the transitions of a story whose every claim-bearing line was blocked."""
    by_story: dict[UUID, list[DraftLine]] = defaultdict(list)
    for ln in lines:
        by_story[ln.story_id].append(ln)
    for story_lines in by_story.values():
        factual = [ln for ln in story_lines if ln.claims]
        if factual and all(ln.id in blocks for ln in factual):
            for ln in story_lines:
                if ln.id not in blocks:
                    blocks[ln.id] = Block(
                        ln.id,
                        ln.order,
                        BlockRule.story_dropped,
                        "every factual line of this story was blocked",
                    )


# ---- entry point ----------------------------------------------------------------------------


async def clear_for_air(reviewed: ReviewedScript) -> ClearedScript:
    """Clear a reviewed script for air. Blocked lines are logged with a reason and left out;
    nothing is deleted. Sets the briefing to ``cleared``, or ``failed`` if nothing survives."""
    settings = get_settings()
    script = reviewed.script
    lines = sorted(script.lines, key=lambda ln: ln.order)
    with span("standards-desk", "clear_for_air", script.briefing_id, lines=len(lines)) as s:
        stored = await load_stored([ln.id for ln in lines])
        blocks: dict[UUID, Block] = {}
        for ln in lines:
            hit = check_line(
                ln,
                stored,
                settings.standards_max_copied_words,
                settings.standards_max_transition_words,
            )
            if hit:
                blocks[ln.id] = Block(ln.id, ln.order, hit[0], hit[1])
        drop_orphaned_stories(lines, blocks)

        blocked = tuple(sorted(blocks.values(), key=lambda b: b.order))
        claims_of = {ln.id: [c.id for c in ln.claims] for ln in lines}
        for b in blocked:
            with span(
                "standards-desk",
                "block_line",
                line_id=b.line_id,
                order=b.order,
                rule=b.rule.value,
                reason=b.reason,
                claim_ids=claims_of[b.line_id],
            ):
                pass
        cleared = tuple(
            ClearedLine(ln.id, ln.story_id, ln.order, ln.text, tuple(c.id for c in ln.claims))
            for ln in lines
            if ln.id not in blocks
        )
        rules: dict[str, int] = defaultdict(int)
        for b in blocked:
            rules[b.rule.value] += 1
        s.set(cleared=len(cleared), blocked=len(blocked), rules=dict(rules))
        if not cleared:
            await set_status(script.briefing_id, BriefingStatus.failed)
            raise NotClearedError(f"all {len(lines)} lines were blocked", blocked)
        await set_status(script.briefing_id, BriefingStatus.cleared)
    return ClearedScript._issue(_CLEARANCE, script.briefing_id, cleared, blocked)
