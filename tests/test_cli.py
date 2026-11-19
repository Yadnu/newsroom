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
from app.db.models import Verdict
from app.editor import ClaimVerdict, EvidencePassage, ReviewedScript
from app.producer import NoStoriesError, Rundown, RundownItem
from app.reporter.ingest import IngestReport
from app.reporter.rank import StorySourceRef, TopStory
from app.shared.llm import LLMConfigError
from app.writer import DraftClaim, DraftLine, Script, WriterError

runner = CliRunner()
WHEN = datetime(2026, 11, 16, 9, 30, tzinfo=UTC)


def _story(title: str, outlets: list[str]) -> TopStory:
    refs = [
        StorySourceRef(
            outlet=o, title=f"{title} ({o})", url=f"https://{o}.test/x", published_at=WHEN
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


# ---- brief ----------------------------------------------------------------------------------

CHECKS_OK = dict.fromkeys(("supported", "faithful", "attributed", "fresh", "corroborated"), True)


def _verdict(claim: DraftClaim, verdict: Verdict, evidence: list[EvidencePassage]) -> ClaimVerdict:
    return ClaimVerdict(
        claim_id=claim.id,
        verdict=verdict,
        score=0.9 if verdict == Verdict.approved else 0.4,
        reason="ok" if verdict == Verdict.approved else "needs attribution",
        checks=CHECKS_OK,
        sensitive=False,
        evidence=evidence,
    )


@pytest.fixture
def brief_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    story = _story("Chip launch", ["Wired", "BBC"])
    wired, bbc = story.sources
    rundown = Rundown(
        briefing_id=uuid4(),
        minutes=3,
        items=[
            RundownItem(
                story_id=story.id,
                order=0,
                target_seconds=180,
                title=story.title,
                sources=story.sources,
            )
        ],
    )
    c1 = DraftClaim(id=uuid4(), text="The chip ships in March.", source_ids=[wired.id, bbc.id])
    c2 = DraftClaim(id=uuid4(), text="It is twice as fast.", source_ids=[bbc.id])
    line1 = DraftLine(
        id=uuid4(), story_id=story.id, order=0, text="Chips ship in March.", claims=[c1]
    )
    line2 = DraftLine(id=uuid4(), story_id=story.id, order=1, text="Twice as fast.", claims=[c2])
    script = Script(briefing_id=rundown.briefing_id, lines=[line1, line2])
    reviewed = ReviewedScript(
        script=script,
        verdicts=[
            _verdict(
                c1,
                Verdict.approved,
                [EvidencePassage(source_id=wired.id, outlet="Wired", passage="p", score=0.8)],
            ),
            _verdict(c2, Verdict.rewrite, []),
        ],
        rounds=2,
    )
    seen: dict[str, Any] = {"steps": []}

    async def fake_rundown(minutes: float, topics: list[str] | None = None) -> Rundown:
        seen["steps"].append(("rundown", minutes, topics))
        if seen.get("no_stories"):
            raise NoStoriesError("nothing fresh")
        return rundown

    async def fake_draft(r: Rundown) -> Script:
        seen["steps"].append("draft")
        if seen.get("writer_fails"):
            raise WriterError("no item could be drafted")
        return script

    async def fake_review(s: Script) -> ReviewedScript:
        seen["steps"].append("review")
        return reviewed

    monkeypatch.setattr(cli, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "build_rundown", fake_rundown)
    monkeypatch.setattr(cli, "draft_script", fake_draft)
    monkeypatch.setattr(cli, "review_script", fake_review)
    seen["c1"], seen["c2"] = c1, c2
    return seen


def test_brief_prints_verdict_and_source_per_claim(brief_calls: dict[str, Any]) -> None:
    result = runner.invoke(cli.app, ["brief", "--minutes", "3"])
    assert result.exit_code == 0, result.output
    assert brief_calls["steps"] == [("rundown", 3.0, None), "draft", "review"]
    out = result.stdout
    assert "Chip launch" in out
    approved = next(ln for ln in out.splitlines() if "ships in March" in ln)
    assert "approved" in approved and "(Wired)" in approved  # evidence source, not every citation
    rewrite = next(ln for ln in out.splitlines() if "twice as fast" in ln)
    assert "rewrite" in rewrite and "(BBC)" in rewrite  # no evidence: falls back to cited source
    assert "needs attribution" in out
    assert "approved 1, rewrite 1, rejected 0" in out


def test_brief_json(brief_calls: dict[str, Any]) -> None:
    result = runner.invoke(cli.app, ["brief", "-t", "chips", "-t", "ai", "--json"])
    assert result.exit_code == 0, result.output
    assert brief_calls["steps"][0] == ("rundown", 3.0, ["chips", "ai"])
    report = json.loads(result.stdout)
    assert report["rounds"] == 2 and report["counts"]["approved"] == 1
    (first, second) = report["lines"]
    assert first["claims"][0]["verdict"] == "approved"
    assert first["claims"][0]["sources"] == [{"outlet": "Wired", "url": "https://Wired.test/x"}]
    assert second["claims"][0]["sources"][0]["outlet"] == "BBC"


def test_brief_claim_without_verdict_is_pending(brief_calls: dict[str, Any]) -> None:
    rundown = Rundown(briefing_id=uuid4(), minutes=1, items=[])
    c = DraftClaim(id=uuid4(), text="x", source_ids=[uuid4()])
    line = DraftLine(id=uuid4(), story_id=uuid4(), order=0, text="x", claims=[c])
    reviewed = ReviewedScript(
        script=Script(briefing_id=rundown.briefing_id, lines=[line]), verdicts=[], rounds=0
    )
    (claim,) = cli.brief_report(rundown, reviewed)["lines"][0]["claims"]
    assert claim["verdict"] == "pending" and claim["sources"] == [] and claim["score"] is None


def test_brief_no_stories_exits_nonzero(brief_calls: dict[str, Any]) -> None:
    brief_calls["no_stories"] = True
    result = runner.invoke(cli.app, ["brief"])
    assert result.exit_code == 1
    assert "--refresh" in result.stderr
    assert "draft" not in brief_calls["steps"]


def test_brief_writer_failure_exits_nonzero(brief_calls: dict[str, Any]) -> None:
    brief_calls["writer_fails"] = True
    result = runner.invoke(cli.app, ["brief"])
    assert result.exit_code == 1
    assert "Writer failed" in result.stderr
