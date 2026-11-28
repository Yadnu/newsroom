"""Telecast audio retention (task 9.1). DB side faked; SQL in tests/integration/test_press_db.py."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

import app.press.media as media
from app import worker
from app.config import Settings

NOW = datetime(2026, 11, 30, 12, 0, tzinfo=UTC)


def test_orphan_files_skip_referenced_and_recent_files() -> None:
    old, new = NOW - timedelta(hours=3), NOW - timedelta(minutes=10)
    files = [("telecasts/a.wav", old), ("telecasts/b.wav", old), ("telecasts/c.wav", new)]
    assert media.orphan_files(files, {"telecasts/a.wav"}, NOW) == ["telecasts/b.wav"]


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """A media folder with two telecast files, one orphan and one fresh orphan."""
    folder = tmp_path / "telecasts"
    folder.mkdir()
    old_id, keep_id = uuid4(), uuid4()
    for name in (f"{old_id}.wav", f"{keep_id}.wav", "orphan.wav", "writing.wav"):
        (folder / name).write_bytes(b"x" * 1000)
    hours_ago = (NOW - timedelta(hours=5)).timestamp()
    for name in (f"{old_id}.wav", f"{keep_id}.wav", "orphan.wav"):
        os.utime(folder / name, (hours_ago, hours_ago))
    os.utime(folder / "writing.wav", (NOW.timestamp(), NOW.timestamp()))
    state: dict[str, Any] = {"marked": [], "cutoffs": []}

    async def expired(cutoff: datetime) -> list[tuple[UUID, str]]:
        state["cutoffs"].append(cutoff)
        return [(old_id, f"telecasts/{old_id}.wav")]

    async def referenced() -> set[str]:
        return {f"telecasts/{old_id}.wav", f"telecasts/{keep_id}.wav"}

    async def mark(ids: list[UUID]) -> None:
        state["marked"].extend(ids)

    monkeypatch.setattr(media, "expired_rows", expired)
    monkeypatch.setattr(media, "referenced_paths", referenced)
    monkeypatch.setattr(media, "mark_expired", mark)
    monkeypatch.setattr(
        media, "get_settings", lambda: Settings(_env_file=None, media_dir=str(tmp_path))
    )
    state.update(folder=folder, old_id=old_id, keep_id=keep_id)
    return state


async def test_cleanup_removes_expired_audio_and_old_orphans(store: dict[str, Any]) -> None:
    report = await media.cleanup_media(7, now=NOW)
    folder = store["folder"]
    assert (report.expired, report.orphans, report.bytes_freed) == (1, 1, 2000)
    assert store["marked"] == [store["old_id"]]
    assert store["cutoffs"] == [NOW - timedelta(days=7)]
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [f"{store['keep_id']}.wav", "writing.wav"]
    )


async def test_dry_run_counts_without_deleting(store: dict[str, Any]) -> None:
    report = await media.cleanup_media(7, dry_run=True, now=NOW)
    assert (report.expired, report.orphans, report.dry_run) == (1, 1, True)
    assert store["marked"] == []
    assert len(list(store["folder"].iterdir())) == 4


async def test_zero_days_keeps_everything(store: dict[str, Any]) -> None:
    report = await media.cleanup_media(0, now=NOW)
    assert (report.expired, report.orphans) == (0, 0)
    assert store["cutoffs"] == []


async def test_cleanup_job_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(days: float | None = None, **_: Any) -> media.MediaCleanup:
        return media.MediaCleanup(expired=2, orphans=1, bytes_freed=3)

    monkeypatch.setattr(worker, "cleanup_media", fake)
    assert await worker.cleanup_job({}) == {"expired": 2, "orphans": 1, "bytes_freed": 3}


async def test_cleanup_removes_old_answer_audio(store: dict[str, Any], tmp_path: Path) -> None:
    """Answers to readers' questions (task 9.6) are never referenced: gone after the grace."""
    answers = tmp_path / "answers"
    answers.mkdir()
    (answers / "old.wav").write_bytes(b"y" * 10)
    (answers / "new.wav").write_bytes(b"y" * 10)
    hours_ago = (NOW - timedelta(hours=2)).timestamp()
    os.utime(answers / "old.wav", (hours_ago, hours_ago))
    os.utime(answers / "new.wav", (NOW.timestamp(), NOW.timestamp()))
    report = await media.cleanup_media(7, now=NOW)
    assert report.orphans == 2  # telecasts/orphan.wav and answers/old.wav
    assert [p.name for p in answers.iterdir()] == ["new.wav"]
