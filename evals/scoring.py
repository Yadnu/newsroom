"""Load the judge eval set and score results. Pure functions, unit-tested in tests/test_evals.py.

A claim is *flagged* when the judge's verdict is anything but ``approved`` (rewrite or rejected:
it does not air as written). ``pending`` means the judge call failed; such cases are counted as
errors and left out of the metrics.

- catch rate: planted falsehoods flagged / planted falsehoods judged
- recall: claims expected ``flag`` that were flagged / claims expected ``flag`` (planted included)
- precision: flagged claims that were expected ``flag`` / all flagged claims
- false flag rate: claims expected ``approve`` that were flagged / claims expected ``approve``
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

Expect = Literal["approve", "flag"]
KINDS = (
    "supported",
    "unattributed",
    "distorted",
    "unsupported",
    "stale",
    "sensitive_single",
    "planted",
)


@dataclass(frozen=True, slots=True)
class EvalPassage:
    outlet: str
    published: datetime
    text: str


@dataclass(frozen=True, slots=True)
class EvalCase:
    id: str
    story: str
    text: str
    expect: Expect
    kind: str
    passages: tuple[EvalPassage, ...]


@dataclass(frozen=True, slots=True)
class EvalSet:
    version: str
    today: date
    cases: tuple[EvalCase, ...]


def load(path: Path) -> EvalSet:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for story in raw["stories"]:
        passages = tuple(
            EvalPassage(
                outlet=p["outlet"],
                published=datetime.fromisoformat(p["published"] + "T12:00:00+00:00"),
                text=p["text"],
            )
            for p in story["passages"]
        )
        for n, c in enumerate(story["claims"], 1):
            if c["expect"] not in ("approve", "flag") or c["kind"] not in KINDS:
                raise ValueError(f"{story['id']} claim {n}: bad expect/kind {c}")
            if (c["kind"] == "supported") != (c["expect"] == "approve"):
                raise ValueError(f"{story['id']} claim {n}: only 'supported' claims expect approve")
            cases.append(
                EvalCase(
                    f"{story['id']}-c{n}", story["id"], c["text"], c["expect"], c["kind"], passages
                )
            )
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case ids")
    return EvalSet(raw["version"], date.fromisoformat(raw["today"]), tuple(cases))


def prompt_version(*files: Path) -> str:
    """Short hash of the judge prompt files, for the eval table."""
    h = hashlib.sha256()
    for f in files:
        h.update(f.read_bytes())
    return h.hexdigest()[:8]


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def score(cases: list[EvalCase], verdicts: dict[str, str]) -> dict[str, Any]:
    """``verdicts`` maps case id -> verdict value. Cases without a verdict are ignored."""
    judged = [c for c in cases if c.id in verdicts and verdicts[c.id] != "pending"]
    errors = sum(1 for c in cases if verdicts.get(c.id) == "pending")

    def flagged(c: EvalCase) -> bool:
        return verdicts[c.id] != "approved"

    planted = [c for c in judged if c.kind == "planted"]
    should_flag = [c for c in judged if c.expect == "flag"]
    should_approve = [c for c in judged if c.expect == "approve"]
    all_flagged = [c for c in judged if flagged(c)]
    by_kind = {}
    for kind in KINDS:
        group = [c for c in judged if c.kind == kind]
        if group:
            right = sum(flagged(c) == (c.expect == "flag") for c in group)
            by_kind[kind] = {
                "n": len(group),
                "correct": right,
                "accuracy": _ratio(right, len(group)),
            }
    return {
        "judged": len(judged),
        "errors": errors,
        "catch_rate": _ratio(sum(flagged(c) for c in planted), len(planted)),
        "planted": len(planted),
        "recall": _ratio(sum(flagged(c) for c in should_flag), len(should_flag)),
        "precision": _ratio(sum(c.expect == "flag" for c in all_flagged), len(all_flagged)),
        "false_flag_rate": _ratio(sum(flagged(c) for c in should_approve), len(should_approve)),
        "accuracy": _ratio(sum(flagged(c) == (c.expect == "flag") for c in judged), len(judged)),
        "by_kind": by_kind,
        "missed_planted": [c.id for c in planted if not flagged(c)],
        "false_flags": [c.id for c in should_approve if flagged(c)],
    }
