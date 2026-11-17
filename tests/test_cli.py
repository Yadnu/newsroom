import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from typer.testing import CliRunner

import app.cli as cli
from app.reporter.ingest import IngestReport
from app.reporter.rank import StorySourceRef, TopStory
from app.shared.llm import LLMConfigError

runner = CliRunner()
WHEN = datetime(2026, 11, 16, 9, 30, tzinfo=UTC)


def _story(title: str, outlets: list[str]) -> TopStory:
    refs = [
        StorySourceRef(
            id=uuid4(),
            outlet=o,
            title=f"{title} ({o})",
            url=f"https://{o}.test/x",
            published_at=WHEN,
        )
        for o in outlets
    ]
    return TopStory(
        id=uuid4(),
        title=title,
        n_sources=len(refs),
        outlets=sorted(set(outlets)),
        latest_at=WHEN,
        sources=refs,
    )


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {"refresh": []}

    async def fake_top(limit: int, window_hours: int, min_sources: int) -> list[TopStory]:
        seen["top"] = (limit, window_hours, min_sources)
        return seen.get("stories", [])

    async def fake_ingest() -> IngestReport:
        seen["refresh"].append("ingest")
        return IngestReport(new_sources=5)

    async def fake_embed() -> int:
        seen["refresh"].append("embed")
        if seen.get("no_key"):
            raise LLMConfigError("NEWSROOM_VOYAGE_API_KEY is not set")
        return 5

    async def fake_cluster(window_hours: int) -> list[object]:
        seen["refresh"].append(f"cluster:{window_hours}")
        return [object()]

    # structlog caches loggers; configuring it against CliRunner's temp streams breaks later tests.
    monkeypatch.setattr(cli, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "top_stories", fake_top)
    monkeypatch.setattr(cli, "ingest_feeds", fake_ingest)
    monkeypatch.setattr(cli, "embed_pending_sources", fake_embed)
    monkeypatch.setattr(cli, "cluster_stories", fake_cluster)
    return seen


def test_stories_table(calls: dict[str, Any]) -> None:
    calls["stories"] = [_story("Chip launch", ["Wired", "BBC"]), _story("AI probe", ["Ars", "Ars"])]
    result = runner.invoke(cli.app, ["stories", "--top", "10"])
    assert result.exit_code == 0, result.output
    assert calls["top"] == (10, 24, 2)
    assert calls["refresh"] == []
    assert "Chip launch" in result.output and "BBC, Wired" in result.output
    assert result.output.index("Chip launch") < result.output.index("AI probe")


def test_stories_json_includes_sources(calls: dict[str, Any]) -> None:
    calls["stories"] = [_story("Chip launch", ["Wired", "BBC"])]
    result = runner.invoke(
        cli.app, ["stories", "-n", "3", "--hours", "12", "--min-sources", "1", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert calls["top"] == (3, 12, 1)
    (story,) = json.loads(result.stdout)
    assert story["title"] == "Chip launch" and story["n_sources"] == 2
    assert {s["url"] for s in story["sources"]} == {"https://Wired.test/x", "https://BBC.test/x"}


def test_refresh_runs_pipeline_first(calls: dict[str, Any]) -> None:
    calls["stories"] = [_story("x", ["A", "B"])]
    result = runner.invoke(cli.app, ["stories", "--refresh", "--hours", "6"])
    assert result.exit_code == 0, result.output
    assert calls["refresh"] == ["ingest", "embed", "cluster:6"]
    assert "5 new sources" in result.stderr


def test_refresh_without_voyage_key_warns_and_continues(calls: dict[str, Any]) -> None:
    calls["no_key"] = True
    calls["stories"] = [_story("x", ["A", "B"])]
    result = runner.invoke(cli.app, ["stories", "--refresh"])
    assert result.exit_code == 0, result.output
    assert "NEWSROOM_VOYAGE_API_KEY" in result.stderr


def test_no_stories_exits_nonzero_with_hint(calls: dict[str, Any]) -> None:
    result = runner.invoke(cli.app, ["stories"])
    assert result.exit_code == 1
    assert "--refresh" in result.stderr


def test_top_must_be_positive(calls: dict[str, Any]) -> None:
    assert runner.invoke(cli.app, ["stories", "--top", "0"]).exit_code != 0
