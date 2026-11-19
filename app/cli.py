"""``newsroom`` command line. Installed as a script: ``uv run newsroom --help``."""

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from app.archive import start_archive, stop_archive
from app.config import get_settings
from app.db.models import Verdict
from app.editor import ClaimVerdict, ReviewedScript, review_script
from app.log import configure_logging
from app.producer import NoStoriesError, Rundown, build_rundown
from app.reporter import cluster_stories, embed_pending_sources, ingest_feeds
from app.reporter.rank import StorySourceRef, TopStory, top_stories
from app.shared import llm
from app.standards_desk import Block, BriefingNotFoundError, NotClearedError, clear_for_air
from app.writer import DraftClaim, WriterError, draft_script

app = typer.Typer(help="Newsroom: voice-first AI news anchor.", no_args_is_help=True)
console = Console()
err = Console(stderr=True)


@app.callback()
def _root() -> None:
    """Keeps ``stories`` a subcommand even while it is the only one."""


def _run[T](fn: Callable[[], Awaitable[T]]) -> T:
    async def wrapped() -> T:
        await start_archive()
        try:
            return await fn()
        finally:
            await stop_archive()
            await llm.aclose()

    return asyncio.run(wrapped())


async def refresh(window_hours: int) -> dict[str, Any]:
    """Ingest, embed and cluster, as the scheduled worker does."""
    report = await ingest_feeds()
    try:
        embedded = await embed_pending_sources()
    except llm.LLMConfigError as e:
        err.print(f"[yellow]Skipping embeddings:[/] {e}")
        embedded = 0
    touched = await cluster_stories(window_hours)
    return {
        "new_sources": report.new_sources,
        "embedded": embedded,
        "stories_touched": len(touched),
    }


@app.command()
def stories(
    top: Annotated[int, typer.Option("--top", "-n", min=1, help="How many stories.")] = 10,
    hours: Annotated[int, typer.Option(min=1, help="Only stories with a source this recent.")] = 24,
    min_sources: Annotated[int, typer.Option(min=1, help="Minimum sources per story.")] = 2,
    do_refresh: Annotated[
        bool, typer.Option("--refresh", help="Ingest, embed and cluster first.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")] = False,
) -> None:
    """Today's top stories, ranked by number of outlets, then sources, then recency."""
    configure_logging(get_settings(), stream=sys.stderr)

    async def go() -> list[TopStory]:
        if do_refresh:
            summary = await refresh(hours)
            err.print(
                f"refreshed: {summary['new_sources']} new sources, {summary['embedded']} embedded,"
                f" {summary['stories_touched']} stories touched"
            )
        return await top_stories(limit=top, window_hours=hours, min_sources=min_sources)

    result = _run(go)
    if as_json:
        typer.echo(json.dumps([s.model_dump(mode="json") for s in result], indent=2))
        return
    if not result:
        err.print(
            f"No stories in the last {hours}h with {min_sources}+ sources."
            " Try --refresh, or check that sources are embedded (NEWSROOM_VOYAGE_API_KEY)."
        )
        raise typer.Exit(code=1)
    table = Table(title=f"Top {len(result)} stories, last {hours}h")
    table.add_column("#", justify="right")
    table.add_column("Story")
    table.add_column("Sources", justify="right")
    table.add_column("Outlets")
    table.add_column("Latest (UTC)")
    for i, s in enumerate(result, 1):
        table.add_row(
            str(i),
            s.title,
            str(s.n_sources),
            ", ".join(s.outlets),
            s.latest_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


VERDICT_STYLE = {
    Verdict.approved: "green",
    Verdict.rewrite: "yellow",
    Verdict.rejected: "red",
    Verdict.pending: "dim",
}


def claim_sources(
    claim: DraftClaim, verdict: ClaimVerdict | None, refs: dict[UUID, StorySourceRef]
) -> list[StorySourceRef]:
    """The sources behind a claim: the evidence the judge cited, else the Writer's citations."""
    ids = [e.source_id for e in verdict.evidence] if verdict and verdict.evidence else []
    ids = ids or claim.source_ids
    return [refs[i] for i in dict.fromkeys(ids) if i in refs]


def brief_report(
    rundown: Rundown, reviewed: ReviewedScript, blocks: Sequence[Block] = ()
) -> dict[str, Any]:
    """Plain data for printing: stories in rundown order, each line with its claims and
    whether the Standards Desk cleared it for air."""
    blocked = {b.line_id: b for b in blocks}
    refs = {s.id: s for item in rundown.items for s in item.sources}
    verdicts = {v.claim_id: v for v in reviewed.verdicts}
    titles = {item.story_id: item.title for item in rundown.items}
    lines = []
    for line in sorted(reviewed.script.lines, key=lambda x: x.order):
        claims = []
        for c in line.claims:
            v = verdicts.get(c.id)
            claims.append(
                {
                    "text": c.text,
                    "verdict": (v.verdict if v else Verdict.pending).value,
                    "score": v.score if v else None,
                    "reason": v.reason if v else "",
                    "sources": [
                        {"outlet": s.outlet, "url": s.url} for s in claim_sources(c, v, refs)
                    ],
                }
            )
        lines.append(
            {
                "story": titles.get(line.story_id, ""),
                "order": line.order,
                "text": line.text,
                "on_air": line.id not in blocked,
                "block": (
                    {"rule": blocked[line.id].rule.value, "reason": blocked[line.id].reason}
                    if line.id in blocked
                    else None
                ),
                "claims": claims,
            }
        )
    return {
        "briefing_id": str(rundown.briefing_id),
        "minutes": rundown.minutes,
        "stories": len(rundown.items),
        "rounds": reviewed.rounds,
        "counts": {v.value: reviewed.count(v) for v in Verdict},
        "cleared": sum(ln["on_air"] for ln in lines),
        "lines": lines,
    }


def print_brief(report: dict[str, Any]) -> None:
    story = None
    for line in report["lines"]:
        if line["story"] != story:
            story = line["story"]
            console.print(f"\n[bold]{escape(story)}[/]")
        if line["on_air"]:
            console.print(f"  {escape(line['text'])}")
        else:
            console.print(f"  [strike dim]{escape(line['text'])}[/]")
            block = line["block"]
            console.print(f"    [red]BLOCKED {block['rule']}[/]: [dim]{escape(block['reason'])}[/]")
        for c in line["claims"]:
            style = VERDICT_STYLE[Verdict(c["verdict"])]
            score = f" {c['score']:.2f}" if c["score"] is not None else ""
            outlets = ", ".join(s["outlet"] for s in c["sources"]) or "no source"
            console.print(
                f"    [{style}]{c['verdict']:<8}[/]{score}  {escape(c['text'])}"
                f"  [dim]({escape(outlets)})[/]"
            )
            if c["verdict"] != Verdict.approved and c["reason"]:
                console.print(f"             [dim]{escape(c['reason'])}[/]")
    counts = report["counts"]
    console.print(
        f"\nbriefing {report['briefing_id']}: {report['stories']} stories,"
        f" {len(report['lines'])} lines, rewrite rounds {report['rounds']}."
        f" approved {counts['approved']}, rewrite {counts['rewrite']},"
        f" rejected {counts['rejected']}, pending {counts['pending']}."
        f" Cleared for air {report['cleared']}/{len(report['lines'])} lines"
    )


@app.command()
def brief(
    minutes: Annotated[float, typer.Option(min=0.25, help="Target length in minutes.")] = 3.0,
    topic: Annotated[
        list[str] | None, typer.Option("--topic", "-t", help="Only stories matching this.")
    ] = None,
    do_refresh: Annotated[
        bool, typer.Option("--refresh", help="Ingest, embed and cluster first.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of text.")] = False,
) -> None:
    """Build a rundown, write the script, fact-check it, and print each claim's verdict."""
    configure_logging(get_settings(), stream=sys.stderr)

    async def go() -> tuple[Rundown, ReviewedScript, tuple[Block, ...], bool]:
        if do_refresh:
            summary = await refresh(get_settings().producer_freshness_hours)
            err.print(f"refreshed: {summary['new_sources']} new sources")
        rundown = await build_rundown(minutes, topic or None)
        err.print(f"rundown: {len(rundown.items)} stories, {rundown.total_seconds}s")
        script = await draft_script(rundown)
        err.print(f"drafted: {len(script.lines)} lines; judging")
        reviewed = await review_script(script)
        try:
            cleared = await clear_for_air(reviewed)
        except NotClearedError as e:
            return rundown, reviewed, e.blocked, False
        return rundown, reviewed, cleared.blocked, True

    try:
        rundown, reviewed, blocks, any_cleared = _run(go)
    except NoStoriesError as e:
        err.print(f"[red]No stories:[/] {e}. Try --refresh, or `newsroom stories` to check.")
        raise typer.Exit(code=1) from e
    except WriterError as e:
        err.print(f"[red]Writer failed:[/] {e}")
        raise typer.Exit(code=1) from e
    report = brief_report(rundown, reviewed, blocks)
    if as_json:
        typer.echo(json.dumps(report, indent=2))
    else:
        print_brief(report)
    if not any_cleared:
        err.print("[red]Nothing cleared for air:[/] every line was blocked by the Standards Desk.")
        raise typer.Exit(code=1)


@app.command()
def speak(
    briefing_id: Annotated[str, typer.Argument(help="Briefing to voice.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="WAV file to write.")] = Path(
        "brief.wav"
    ),
) -> None:
    """Clear a stored briefing for air, voice it to a WAV file, and print each line's timing."""
    from app.anchor import AnchorConfigError, WavFileSession
    from app.anchor import speak as voice
    from app.standards_desk import clear_stored

    configure_logging(get_settings(), stream=sys.stderr)
    try:
        bid = UUID(briefing_id)
    except ValueError as e:
        err.print(f"[red]Not a briefing id:[/] {briefing_id}")
        raise typer.Exit(code=2) from e

    async def go() -> Any:
        cleared = await clear_stored(bid)
        err.print(f"cleared {len(cleared.lines)} lines ({len(cleared.blocked)} blocked); speaking")
        session = WavFileSession(out, get_settings().anchor_sample_rate)
        return await voice(cleared, session)

    try:
        report = _run(go)
    except BriefingNotFoundError as e:
        err.print(f"[red]Unknown briefing:[/] {e}")
        raise typer.Exit(code=1) from e
    except NotClearedError as e:
        err.print(f"[red]Nothing cleared for air:[/] {e}")
        raise typer.Exit(code=1) from e
    except AnchorConfigError as e:
        err.print(f"[red]Text-to-speech is not configured:[/] {e}")
        raise typer.Exit(code=1) from e
    for t in report.lines:
        console.print(f"  line {t.order:>2}  {t.start_ms:>7} ms -> {t.end_ms:>7} ms")
    console.print(f"wrote {out} ({report.audio_ms / 1000:.1f} s, {len(report.lines)} lines)")


def main() -> None:
    app()
