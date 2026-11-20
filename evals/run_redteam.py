"""Red team eval (task 6.1): satire, stale and prompt-injection cases against the guardrails.

    uv run python evals/run_redteam.py         # offline: Standards Desk + screen rules (CI gate)
    uv run python evals/run_redteam.py --live  # also the LLM layers: screen_caller + the judge

Offline needs nothing and exits 1 when a gated case is wrong. ``--live`` needs
``NEWSROOM_GROQ_API_KEY``; it reports and records but never fails on LLM results. Results go to
``evals/results/<set>-<prompt hash>.jsonl`` and ``.summary.json``.
"""

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.archive import MemorySink, set_sink  # noqa: E402
from app.editor import judge  # noqa: E402
from app.editor.retrieve import ClaimRef  # noqa: E402
from app.editor.retrieve import Passage as EvidencePassage  # noqa: E402
from app.shared import llm  # noqa: E402
from app.standards_desk.screen import screen_caller  # noqa: E402
from evals.redteam import (  # noqa: E402
    JudgeCase,
    Outcome,
    ScreenCase,
    load,
    offline_failures,
    run_offline,
    score,
)
from evals.scoring import prompt_version  # noqa: E402

PROMPTS = (
    ROOT / "prompts/editor/judge_system.md",
    ROOT / "prompts/editor/judge_user.md",
    ROOT / "prompts/standards/screen_system.md",
    ROOT / "prompts/standards/screen_user.md",
)
_NS = uuid.UUID("5f0c1f5e-0000-4000-8000-00000000e7a2")


def passages_for(case: JudgeCase) -> list[EvidencePassage]:
    return [
        EvidencePassage(uuid.uuid5(_NS, f"{case.id}/{n}"), p.outlet, p.published, p.text, 1.0)
        for n, p in enumerate(case.passages)
    ]


async def judge_one(case: JudgeCase) -> Outcome:
    v = await judge.judge_passages(ClaimRef(uuid.uuid4(), case.claim, []), passages_for(case))
    hit = None if v.verdict.value == "pending" else v.verdict.value != "approved"
    return Outcome(case.id, "judge", case.kind, case.expect, hit, f"{v.verdict.value}: {v.reason}")


async def screen_one(case: ScreenCase) -> Outcome:
    r = await screen_caller(case.transcript, case.intent)
    detail = (
        f"{r.category} ({r.checked_by}): {r.reason}"
        if not r.allowed
        else f"allowed ({r.checked_by})"
    )
    return Outcome(case.id, "screen_live", case.kind, case.expect, not r.allowed, detail)


def show(o: Outcome) -> str:
    mark = "?? " if o.correct is None else ("ok " if o.correct else ("XX " if o.gated else "-- "))
    gap = f" [known gap: {o.known_gap}]" if o.known_gap else ""
    return f"{mark}{o.suite:11} {o.id:9} {o.kind:17} expect {o.expect:7} {o.detail}{gap}"


def save(out: Path, outcomes: list[Outcome], summary: dict[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.dumps(asdict(o) | {"correct": o.correct}) for o in outcomes]
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    out.with_suffix(".summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


async def run(args: argparse.Namespace) -> int:
    rt = load(Path(args.data))
    outcomes = run_offline(rt)
    if args.live:
        judge.today = lambda: rt.today
        set_sink(MemorySink())  # keep traces out of the database
        limit = asyncio.Semaphore(args.concurrency)

        async def screen_bounded(c: ScreenCase) -> Outcome:
            async with limit:
                return await screen_one(c)

        async def judge_bounded(c: JudgeCase) -> Outcome:
            async with limit:
                return await judge_one(c)

        try:
            outcomes += await asyncio.gather(*(screen_bounded(c) for c in rt.screen))
            outcomes += await asyncio.gather(*(judge_bounded(c) for c in rt.judge))
        finally:
            await llm.aclose()

    for o in outcomes:
        if not args.quiet or o.correct is not True:
            print(show(o))
    summary = score(outcomes)
    failures = offline_failures(outcomes)
    print(
        json.dumps(
            {k: {x: y for x, y in v.items() if x != "by_kind"} for k, v in summary.items()},
            indent=2,
        )
    )

    if args.live:
        version = prompt_version(*PROMPTS)
        gw = llm.get_gateway()
        meta = {
            "set": rt.version,
            "prompt_version": version,
            "models": {"judge": gw.model_for("judge"), "screen": gw.model_for("classify")},
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        out = Path(args.out or ROOT / f"evals/results/{rt.version}-{version}.jsonl")
        await asyncio.to_thread(save, out, outcomes, meta | {"suites": summary})
        print(f"results: {out}")
    if failures:
        print(f"\nFAIL: {len(failures)} gated case(s) wrong: {', '.join(o.id for o in failures)}")
        return 1
    print("\noffline gate: pass")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", default=str(ROOT / "evals/data/redteam_v1.json"))
    p.add_argument("--live", action="store_true", help="also run the LLM layers (Groq)")
    p.add_argument("--out", default=None)
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--quiet", action="store_true", help="print only wrong cases")
    sys.exit(asyncio.run(run(p.parse_args())))


if __name__ == "__main__":
    main()
