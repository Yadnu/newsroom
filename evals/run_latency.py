"""Latency report: p50/p95 per pipeline stage from the spans in ``traces`` (task 6.4).

    uv run python evals/run_latency.py              # all recorded spans
    uv run python evals/run_latency.py --days 7     # only the last 7 days

Prints a Markdown table (the one in README.md) and writes ``evals/results/latency.json``.
Failed spans (``error`` set) are left out. Needs ``NEWSROOM_DATABASE_URL``.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db.session import session_scope  # noqa: E402
from evals.latency import STAGES, markdown, summarize  # noqa: E402

QUERY = text(
    "SELECT component, event, latency_ms FROM traces"
    " WHERE latency_ms IS NOT NULL AND error IS NULL AND started_at >= :since"
)


async def fetch(since: datetime) -> list[tuple[str, str, float]]:
    async with session_scope() as session:
        result = await session.exec(QUERY.bindparams(since=since))  # type: ignore[call-overload]
        return [(r[0], r[1], float(r[2])) for r in result]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=float, help="only spans from the last N days")
    parser.add_argument("--out", type=Path, default=ROOT / "evals/results/latency.json")
    args = parser.parse_args()
    now = datetime.now(UTC)
    since = now - timedelta(days=args.days) if args.days else datetime(1970, 1, 1, tzinfo=UTC)
    stats = summarize(asyncio.run(fetch(since)), STAGES)
    print(markdown(stats))
    args.out.write_text(
        json.dumps(
            {
                "run_at": now.isoformat(timespec="seconds"),
                "since": since.isoformat(timespec="seconds"),
                "stages": [
                    {
                        "path": s.stage.path,
                        "span": f"{s.stage.component}/{s.stage.event}",
                        "label": s.stage.label,
                        "n": s.n,
                        "p50_ms": None if s.p50_ms is None else round(s.p50_ms),
                        "p95_ms": None if s.p95_ms is None else round(s.p95_ms),
                    }
                    for s in stats
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
