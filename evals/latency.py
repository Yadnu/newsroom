"""Latency p50/p95 per pipeline stage, from span latencies in ``traces`` (task 6.4).

Pure functions, unit-tested in tests/test_latency.py; ``evals/run_latency.py`` reads the database.
Percentiles interpolate linearly between ranks (the same as Postgres ``percentile_cont``).
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Stage:
    path: str  # "briefing" or "answer"
    component: str
    event: str
    label: str


STAGES: tuple[Stage, ...] = (
    Stage("briefing", "reporter", "ingest_feeds", "Fetch and dedupe RSS feeds"),
    Stage("briefing", "writer", "draft_script", "Write the script"),
    Stage("briefing", "editor", "judge_claim", "Judge one claim"),
    Stage("briefing", "editor", "review_script", "Judge every claim + rewrite loop"),
    Stage("briefing", "standards-desk", "clear_for_air", "Clear for air"),
    Stage("briefing", "anchor", "line", "Voice one line (TTS)"),
    Stage("answer", "caller", "question", "Classify + screen a question (after STT)"),
    Stage("answer", "producer", "answer", "Question to cleared answer"),
)


@dataclass(frozen=True, slots=True)
class StageStats:
    stage: Stage
    n: int
    p50_ms: float | None
    p95_ms: float | None


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile, ``q`` in [0, 1]. None for no values."""
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"q must be in [0, 1], got {q}")
    if not values:
        return None
    xs = sorted(values)
    pos = q * (len(xs) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def summarize(
    rows: Iterable[tuple[str, str, float]], stages: Sequence[Stage] = STAGES
) -> list[StageStats]:
    """``rows`` are (component, event, latency_ms) of successful spans; one result per stage."""
    by_key: dict[tuple[str, str], list[float]] = {}
    for component, event, ms in rows:
        by_key.setdefault((component, event), []).append(ms)
    out = []
    for st in stages:
        xs = by_key.get((st.component, st.event), [])
        out.append(StageStats(st, len(xs), percentile(xs, 0.5), percentile(xs, 0.95)))
    return out


def _fmt(ms: float | None) -> str:
    if ms is None:
        return "-"
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:.0f} ms"


def markdown(stats: Sequence[StageStats]) -> str:
    lines = ["| Path | Stage | n | p50 | p95 |", "| --- | --- | --- | --- | --- |"]
    for s in stats:
        lines.append(
            f"| {s.stage.path} | {s.stage.label} (`{s.stage.component}/{s.stage.event}`) "
            f"| {s.n} | {_fmt(s.p50_ms)} | {_fmt(s.p95_ms)} |"
        )
    return "\n".join(lines)
