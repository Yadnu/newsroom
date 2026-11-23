"""``newsroom`` command line. Installed as a script: ``uv run newsroom --help``."""

import asyncio
import codecs
import io
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
from app.standards_desk.corrections import queue_corrections
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
                "story": "Corrections"
                if line.kind == "correction"
                else titles.get(line.story_id, ""),
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
        # On-air corrections of earlier briefings air first (task 6.2, decision 0023).
        if corrections := await queue_corrections(rundown.briefing_id):
            err.print(f"corrections: {len(corrections)} queued at the top")
            lines = [*corrections, *reviewed.script.lines]
            reviewed = reviewed.model_copy(
                update={"script": reviewed.script.model_copy(update={"lines": lines})}
            )
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


@app.command()
def ask(
    briefing_id: Annotated[str, typer.Option("--briefing", "-b", help="Briefing being heard.")],
    wav: Annotated[Path, typer.Option("--wav", help="Mono 16-bit WAV of the spoken question.")],
    realtime: Annotated[
        bool, typer.Option("--realtime", help="Stream at speaking pace, like a live mic.")
    ] = False,
) -> None:
    """Transcribe a spoken question and classify it against a briefing's stories."""
    import wave

    from app.caller import CallerQuestion, Interim, context_for, listen
    from app.caller.types import CallerConfigError
    from app.standards_desk import clear_stored

    configure_logging(get_settings(), stream=sys.stderr)
    settings = get_settings()
    with wave.open(str(wav), "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (
            1,
            2,
            settings.caller_sample_rate,
        ):
            err.print(f"[red]Need a mono 16-bit WAV at {settings.caller_sample_rate} Hz[/]")
            raise typer.Exit(code=2)
        pcm = w.readframes(w.getnframes())
    chunk = settings.caller_sample_rate * 2 // 10  # 100 ms

    async def chunks() -> Any:
        for i in range(0, len(pcm), chunk):
            if realtime:
                await asyncio.sleep(0.1)
            yield pcm[i : i + chunk]

    async def go() -> list[CallerQuestion]:
        context = await context_for(await clear_stored(UUID(briefing_id)))
        found: list[CallerQuestion] = []
        async for event in listen(chunks(), context):
            if isinstance(event, Interim):
                err.print(f"[dim]… {escape(event.text)}[/]")
            else:
                found.append(event)
        titles = {s.id: s.title for s in context.stories}
        for q in found:
            title = titles.get(q.story_id, "") if q.story_id else ""
            console.print(f"[bold]{escape(q.transcript)}[/]")
            console.print(f"  intent {q.intent}  story {escape(title) or '-'}")
            if q.restated:
                console.print(f"  restated: {escape(q.restated)}")
            if q.screen is not None:
                verdict = "allowed" if q.screen.allowed else "BLOCKED"
                console.print(
                    f"  screen: {verdict} {q.screen.category} ({q.screen.checked_by})"
                    f" {escape(q.screen.reason)}"
                )
        return found

    try:
        found = _run(go)
    except CallerConfigError as e:
        err.print(f"[red]Speech-to-text is not configured:[/] {e}")
        raise typer.Exit(code=1) from e
    except (BriefingNotFoundError, NotClearedError) as e:
        err.print(f"[red]Cannot use that briefing:[/] {e}")
        raise typer.Exit(code=1) from e
    if not found:
        err.print("No question heard.")
        raise typer.Exit(code=1)


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="What to search the news for.")],
    days: Annotated[int, typer.Option(min=1, max=30, help="How many days back.")] = 7,
) -> None:
    """Live news search (Tavily, Firecrawl for full text); results are stored as sources."""
    from app.reporter.search import search_live

    configure_logging(get_settings(), stream=sys.stderr)
    found = _run(lambda: search_live(query, days=days))
    if not found:
        err.print("Nothing found (or search is not configured: NEWSROOM_TAVILY_API_KEY).")
        raise typer.Exit(code=1)
    for src in found:
        when = src.published_at.strftime("%Y-%m-%d") if src.published_at else "undated"
        console.print(f"[bold]{escape(src.outlet)}[/] {when}  {escape(src.title)}")
        console.print(f"  [dim]{escape(src.url)}[/]")


def _print_retraction(r: Any) -> None:
    if r.already:
        console.print(f"[yellow]already retracted[/] {escape(r.outlet)} {escape(r.url)}")
        return
    console.print(f"[red]retracted[/] {escape(r.outlet)} {escape(r.url)}: {escape(r.reason)}")
    for b in r.briefings:
        console.print(
            f"  briefing {b.briefing_id} ({b.status}): {b.orphaned} orphaned,"
            f" {b.weakened} weakened, {b.on_air} on-air correction(s) due"
        )
    if not r.briefings:
        console.print("  no briefing used it")


@app.command()
def retract(
    source: Annotated[str, typer.Argument(help="Source id or URL.")],
    reason: Annotated[str, typer.Option(help="Why (shown in the Archive).")] = "retracted",
) -> None:
    """Retract a source and flag every briefing whose claims relied on it."""
    from app.reporter.retract import SourceNotFoundError, parse_ref, retract_source

    configure_logging(get_settings(), stream=sys.stderr)
    try:
        report = _run(lambda: retract_source(parse_ref(source), reason))
    except SourceNotFoundError as e:
        err.print(f"[red]{e}[/]")
        raise typer.Exit(code=1) from e
    _print_retraction(report)


@app.command()
def recheck(
    hours: Annotated[int, typer.Option(min=1, help="Sources behind briefings this recent.")] = 48,
) -> None:
    """Re-fetch recently cited sources; retract the ones that are gone or carry a retraction."""
    from app.reporter.retract import recheck_sources

    configure_logging(get_settings(), stream=sys.stderr)
    report = _run(lambda: recheck_sources(hours))
    console.print(
        f"checked {report.checked} sources, {report.unreachable} unreachable (kept),"
        f" {len(report.retracted)} retracted"
    )
    for r in report.retracted:
        _print_retraction(r)


@app.command()
def corrections(
    briefing: Annotated[str | None, typer.Option(help="Only this briefing.")] = None,
    limit: Annotated[int, typer.Option(min=1, max=500)] = 50,
) -> None:
    """Claims affected by retracted sources, newest first."""
    from app.archive import list_corrections

    configure_logging(get_settings(), stream=sys.stderr)
    rows = _run(lambda: list_corrections(UUID(briefing) if briefing else None, limit))
    if not rows:
        console.print("no corrections")
    for c in rows:
        due = (
            ("on air: queued" if c.correction_line_id else "on air: due")
            if c.on_air
            else "not aired"
        )
        console.print(
            f"[bold]{c.impact}[/] {escape(c.claim_text)}  [dim]({escape(c.outlet)}: "
            f"{escape(c.reason or '')}; briefing {c.briefing_id}; {due})[/]"
        )


def utf8_streams(*streams: object) -> None:
    """Switch text streams that cannot encode Unicode (cp1252 on a Windows pipe or redirect) to
    UTF-8, replacing anything still unencodable. Headlines carry characters like U+2011, and a
    print crash would lose the report after the briefing was already stored."""
    for stream in streams:
        if not isinstance(stream, io.TextIOWrapper):
            continue
        if codecs.lookup(stream.encoding).name != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    utf8_streams(sys.stdout, sys.stderr)
    app()
