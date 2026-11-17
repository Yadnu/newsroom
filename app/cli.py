"""``newsroom`` command line. Installed as a script: ``uv run newsroom --help``."""

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from app.archive import start_archive, stop_archive
from app.config import get_settings
from app.log import configure_logging
from app.reporter import cluster_stories, embed_pending_sources, ingest_feeds
from app.reporter.rank import TopStory, top_stories
from app.shared import llm

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


def main() -> None:
    app()
