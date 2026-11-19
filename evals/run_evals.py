"""Judge eval: run the Editor's judge over a labelled claim set and record catch rate etc.

    uv run python evals/run_evals.py                  # full set, resumes a partial run
    uv run python evals/run_evals.py --limit 10 --fresh

Each claim is judged against its story's fixed passages with ``judge_passages()``, so this measures
the judge prompt and model, not retrieval. "Today" is pinned to the eval set's date. Results are
appended to ``evals/results/<set>-<prompt hash>.jsonl`` as they arrive (a rerun skips finished
cases), and the summary goes to ``.summary.json`` next to it. Needs ``NEWSROOM_GROQ_API_KEY``.
"""

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.archive import MemorySink, set_sink  # noqa: E402
from app.db.models import Verdict  # noqa: E402
from app.editor import judge  # noqa: E402
from app.editor.retrieve import ClaimRef, Passage  # noqa: E402
from app.shared import llm  # noqa: E402
from evals.scoring import EvalCase, load, prompt_version, score  # noqa: E402

PROMPTS = (ROOT / "prompts/editor/judge_system.md", ROOT / "prompts/editor/judge_user.md")
_NS = uuid.UUID("5f0c1f5e-0000-4000-8000-000000000e7a")


def passages_for(case: EvalCase) -> list[Passage]:
    return [
        Passage(uuid.uuid5(_NS, f"{case.story}/{p.outlet}"), p.outlet, p.published, p.text, 1.0)
        for p in case.passages
    ]


def previous_results(out: Path, fresh: bool) -> dict[str, str]:
    """Case id -> verdict from an earlier partial run. Failed (pending) calls are redone."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if fresh and out.exists():
        out.unlink()
    done: dict[str, str] = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["verdict"] != Verdict.pending.value:
                done[row["id"]] = row["verdict"]
    return done


def append(out: Path, row: dict[str, object]) -> None:
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


async def run(args: argparse.Namespace) -> int:
    evalset = load(Path(args.data))
    judge.today = lambda: evalset.today  # pin "today" to the set's date
    set_sink(MemorySink())  # offline: keep traces out of the database
    version = prompt_version(*PROMPTS)
    model = llm.get_gateway().model_for("judge")
    out = Path(args.out or ROOT / f"evals/results/{evalset.version}-{version}.jsonl")
    done = await asyncio.to_thread(previous_results, out, args.fresh)
    cases = list(evalset.cases)[: args.limit] if args.limit else list(evalset.cases)
    todo = [c for c in cases if c.id not in done]
    print(
        f"{evalset.version}: {len(cases)} cases, {len(done)} done, {len(todo)} to judge "
        f"(model {model}, prompt {version})",
        flush=True,
    )

    limit = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()
    results = dict(done)

    async def one(case: EvalCase) -> None:
        async with limit:
            v = await judge.judge_passages(
                ClaimRef(uuid.uuid4(), case.text, []), passages_for(case)
            )
        verdict = v.verdict.value
        row: dict[str, object] = {
            "id": case.id,
            "kind": case.kind,
            "expect": case.expect,
            "verdict": verdict,
            "score": v.score,
            "sensitive": v.sensitive,
            "checks": v.checks,
            "reason": v.reason,
            "model": model,
            "prompt_version": version,
        }
        async with lock:
            await asyncio.to_thread(append, out, row)
            results[case.id] = verdict
            mark = "ok " if (verdict != "approved") == (case.expect == "flag") else "XX "
            print(f"{mark}{case.id:8} {case.kind:16} -> {verdict}", flush=True)

    try:
        await asyncio.gather(*(one(c) for c in todo))
    finally:
        await llm.aclose()

    summary = score(cases, results) | {
        "set": evalset.version,
        "prompt_version": version,
        "model": model,
        "cases": len(cases),
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    await asyncio.to_thread(
        out.with_suffix(".summary.json").write_text,
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "by_kind"}, indent=2))
    for kind, stats in summary["by_kind"].items():
        print(f"  {kind:16} {stats['correct']}/{stats['n']}")
    print(
        f"\n| {summary['run_at'][:10]} | {version} ({model}) | {summary['catch_rate']} | "
        f"{summary['precision']} | {summary['recall']} |"
    )
    return 1 if summary["errors"] else 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", default=str(ROOT / "evals/data/judge_v1.json"))
    p.add_argument("--out", default=None)
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--fresh", action="store_true", help="discard a previous partial run")
    sys.exit(asyncio.run(run(p.parse_args())))


if __name__ == "__main__":
    main()
