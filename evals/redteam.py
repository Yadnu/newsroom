"""Red team set (task 6.1): load the cases, run the deterministic layers, score every suite.

Suites in ``evals/data/redteam_v1.json``:

- ``judge``  claim + passages through the Editor's LLM judge (live only). ``flag`` = any verdict but
  ``approved``.
- ``screen`` a listener's question through ``screen_caller``. ``layer: rules`` cases must be
  blocked by the deterministic rules; every ``benign`` case must pass them. ``layer: llm`` only
  counts live.
- ``clear``  one script line through the Standards Desk's ``check_line`` rules (deterministic).

The offline gate (``offline_failures``) is what CI runs on every PR. ``known_gap`` cases are
reported but not gated. Pure functions apart from the rules they call; tested in
``tests/test_redteam.py``.
"""

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from app.standards_desk.clear import StoredClaim, StoredLines, check_line
from app.standards_desk.screen import screen_rules
from app.writer import DraftLine
from app.writer.draft import DraftClaim

JUDGE_KINDS = ("satire", "stale", "injection_passage", "injection_claim")
SCREEN_KINDS = ("injection", "say_on_air", "abusive", "benign")
CLEAR_KINDS = (
    "hijacked_writer",
    "satire",
    "stale",
    "unverified",
    "disguised_fact",
    "long_quote",
    "verbatim",
    "opinion",
    "control",
)
VERDICTS = ("approved", "rewrite", "rejected", "pending")
MAX_COPIED = 12  # Settings.standards_max_copied_words default
MAX_TRANSITION = 10  # Settings.standards_max_transition_words default
_NS = uuid.UUID("5f0c1f5e-0000-4000-8000-0000000000e7")


@dataclass(frozen=True, slots=True)
class Passage:
    outlet: str
    published: datetime
    text: str


@dataclass(frozen=True, slots=True)
class JudgeCase:
    id: str
    kind: str
    expect: Literal["flag", "approve"]
    claim: str
    passages: tuple[Passage, ...]


@dataclass(frozen=True, slots=True)
class ScreenCase:
    id: str
    kind: str
    expect: Literal["block", "allow"]
    transcript: str
    layer: Literal["rules", "llm", "any"] = "any"
    intent: str | None = None


@dataclass(frozen=True, slots=True)
class ClearClaim:
    verdict: str = "approved"
    evidence: int = 1
    live_evidence: int = 1
    stored: bool = True


@dataclass(frozen=True, slots=True)
class ClearCase:
    id: str
    kind: str
    expect: Literal["block", "clear"]
    text: str
    claims: tuple[ClearClaim, ...] = ()
    sources: tuple[str, ...] = ()
    extra_stored: int = 0
    known_gap: str | None = None


@dataclass(frozen=True, slots=True)
class RedTeamSet:
    version: str
    today: date
    judge: tuple[JudgeCase, ...]
    screen: tuple[ScreenCase, ...]
    clear: tuple[ClearCase, ...]


@dataclass(frozen=True, slots=True)
class Outcome:
    """One case's result. ``hit`` = the guard fired (flagged / blocked)."""

    id: str
    suite: str
    kind: str
    expect: str
    hit: bool | None  # None: the call failed (live only)
    detail: str = ""
    gated: bool = False
    known_gap: str | None = None

    @property
    def correct(self) -> bool | None:
        if self.hit is None:
            return None
        return self.hit == (self.expect in ("flag", "block"))


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def load(path: Path) -> RedTeamSet:
    raw = json.loads(path.read_text(encoding="utf-8"))
    judge: list[JudgeCase] = []
    for c in raw["judge"]:
        _check(
            c["kind"] in JUDGE_KINDS and c["expect"] in ("flag", "approve"), f"bad case {c['id']}"
        )
        _check(len(c["passages"]) >= 1, f"{c['id']}: no passages")
        passages = tuple(
            Passage(
                p["outlet"], datetime.fromisoformat(p["published"] + "T12:00:00+00:00"), p["text"]
            )
            for p in c["passages"]
        )
        judge.append(JudgeCase(c["id"], c["kind"], c["expect"], c["claim"], passages))
    screen: list[ScreenCase] = []
    for c in raw["screen"]:
        _check(c["kind"] in SCREEN_KINDS and c["expect"] in ("block", "allow"), f"bad {c['id']}")
        _check((c["kind"] == "benign") == (c["expect"] == "allow"), f"{c['id']}: benign = allow")
        _check(c.get("layer", "any") in ("rules", "llm", "any"), f"{c['id']}: bad layer")
        screen.append(
            ScreenCase(
                c["id"],
                c["kind"],
                c["expect"],
                c["transcript"],
                c.get("layer", "any"),
                c.get("intent"),
            )
        )
    clear: list[ClearCase] = []
    for c in raw["clear"]:
        _check(c["kind"] in CLEAR_KINDS and c["expect"] in ("block", "clear"), f"bad {c['id']}")
        _check((c["kind"] == "control") == (c["expect"] == "clear"), f"{c['id']}: control = clear")
        claims = tuple(ClearClaim(**cl) for cl in c.get("claims", []))
        _check(all(cl.verdict in VERDICTS for cl in claims), f"{c['id']}: bad verdict")
        clear.append(
            ClearCase(
                c["id"],
                c["kind"],
                c["expect"],
                c["text"],
                claims,
                tuple(c.get("sources", [])),
                c.get("extra_stored", 0),
                c.get("known_gap"),
            )
        )
    ids = [c.id for c in judge] + [c.id for c in screen] + [c.id for c in clear]
    _check(len(set(ids)) == len(ids), "duplicate case ids")
    return RedTeamSet(
        raw["version"], date.fromisoformat(raw["today"]), tuple(judge), tuple(screen), tuple(clear)
    )


# ---- deterministic layers ---------------------------------------------------------------------


def _id(*parts: object) -> uuid.UUID:
    return uuid.uuid5(_NS, "/".join(map(str, parts)))


def line_for(case: ClearCase) -> tuple[DraftLine, StoredLines]:
    """The case as a script line plus what Postgres would hold for it."""
    line_id = _id(case.id, "line")
    claims = [
        DraftClaim(id=_id(case.id, n), text=f"claim {n}", source_ids=[])
        for n in range(len(case.claims))
    ]
    stored = StoredLines()
    rows = {
        claims[n].id: StoredClaim(cl.verdict, cl.evidence, cl.live_evidence)
        for n, cl in enumerate(case.claims)
        if cl.stored
    }
    rows |= {
        _id(case.id, "extra", n): StoredClaim("approved", 1, 1) for n in range(case.extra_stored)
    }
    if rows:
        stored.claims[line_id] = rows
    if case.sources:
        stored.sources[line_id] = list(case.sources)
    line = DraftLine(
        id=line_id, story_id=_id(case.id, "story"), order=0, text=case.text, claims=claims
    )
    return line, stored


def run_clear(case: ClearCase) -> Outcome:
    line, stored = line_for(case)
    hit = check_line(line, stored, MAX_COPIED, MAX_TRANSITION)
    detail = f"{hit[0].value}: {hit[1]}" if hit else "cleared"
    return Outcome(
        case.id,
        "clear",
        case.kind,
        case.expect,
        hit is not None,
        detail,
        gated=case.known_gap is None,
        known_gap=case.known_gap,
    )


def run_screen_rules(case: ScreenCase, max_words: int = 80) -> Outcome:
    """Rules only. Gated: rules-layer attacks must be blocked, benign questions must pass."""
    r = screen_rules(case.transcript, case.intent, max_words)
    gated = case.layer == "rules" or case.expect == "allow"
    hit = r is not None
    if not gated and not hit:
        detail = "passed the rules (left to the LLM layer)"
    else:
        detail = f"{r.category}: {r.reason}" if r else "allowed"
    return Outcome(case.id, "screen", case.kind, case.expect, hit, detail, gated=gated)


def run_offline(s: RedTeamSet) -> list[Outcome]:
    return [run_clear(c) for c in s.clear] + [run_screen_rules(c) for c in s.screen]


def offline_failures(outcomes: list[Outcome]) -> list[Outcome]:
    """Gated cases the deterministic layers got wrong. Empty = the CI gate passes."""
    return [o for o in outcomes if o.gated and o.correct is False]


# ---- scoring ----------------------------------------------------------------------------------


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


@dataclass(slots=True)
class SuiteScore:
    n: int = 0
    errors: int = 0
    attacks: int = 0
    caught: int = 0
    controls: int = 0
    false_hits: int = 0
    by_kind: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(dict))
    misses: list[str] = field(default_factory=list)


def score(outcomes: list[Outcome]) -> dict[str, Any]:
    """Per suite: catch rate on attacks, false hit rate on controls, accuracy per kind, misses."""
    suites: dict[str, SuiteScore] = defaultdict(SuiteScore)
    for o in outcomes:
        s = suites[o.suite]
        s.n += 1
        if o.hit is None:
            s.errors += 1
            continue
        k = s.by_kind[o.kind]
        k["n"] = k.get("n", 0) + 1
        k["correct"] = k.get("correct", 0) + bool(o.correct)
        if o.expect in ("flag", "block"):
            s.attacks += 1
            s.caught += o.hit
        else:
            s.controls += 1
            s.false_hits += o.hit
        if not o.correct:
            s.misses.append(o.id)
    return {
        name: {
            "cases": s.n,
            "errors": s.errors,
            "catch_rate": _ratio(s.caught, s.attacks),
            "attacks": s.attacks,
            "false_hit_rate": _ratio(s.false_hits, s.controls),
            "controls": s.controls,
            "by_kind": {k: dict(v) for k, v in sorted(s.by_kind.items())},
            "misses": s.misses,
        }
        for name, s in sorted(suites.items())
    }
