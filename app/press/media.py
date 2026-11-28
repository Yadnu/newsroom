"""Telecast audio retention (task 9.1, decision 0029).

Audio under ``media_dir/telecasts/`` is kept ``press_telecast_retention_days`` (7; 0 = forever).
``cleanup_media()`` deletes older ones and marks their telecasts ``expired`` (the row and its
briefing stay in the Archive; a reader asking again gets a fresh telecast), and removes orphan files
no telecast row points at (older than ``ORPHAN_GRACE``, so a job still writing is never touched),
including answers to readers' questions under ``media_dir/answers/`` (task 9.6).
Run daily by the worker and by ``newsroom cleanup-media``.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, update

from app.archive import span
from app.config import get_settings
from app.db.models import Telecast, utcnow
from app.db.session import get_engine
from app.log import get_logger

ORPHAN_GRACE = timedelta(hours=1)
SUBDIR = "telecasts"
SUBDIRS = (SUBDIR, "answers")  # answer audio (task 9.6): never referenced, gone after the grace

log = get_logger(__name__)
_telecasts = Telecast.__table__  # type: ignore[attr-defined]


@dataclass(slots=True)
class MediaCleanup:
    expired: int = 0  # telecasts whose audio was removed
    orphans: int = 0  # files no telecast pointed at
    bytes_freed: int = 0
    dry_run: bool = False


def orphan_files(
    files: Iterable[tuple[str, datetime]], referenced: set[str], now: datetime
) -> list[str]:
    """Files (relative path, modified at) that no row references, older than the grace."""
    return sorted(
        rel for rel, mtime in files if rel not in referenced and now - mtime > ORPHAN_GRACE
    )


def _media_files(root: Path) -> list[tuple[str, datetime]]:
    out = []
    for sub in SUBDIRS:
        folder = root / sub
        if not folder.is_dir():
            continue
        for f in folder.iterdir():
            if f.is_file():
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=utcnow().tzinfo)
                out.append((f"{sub}/{f.name}", mtime))
    return out


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


async def expired_rows(cutoff: datetime) -> list[tuple[UUID, str]]:
    query = select(_telecasts.c.id, _telecasts.c.audio_path).where(
        _telecasts.c.audio_path.is_not(None), _telecasts.c.created_at < cutoff
    )
    async with get_engine().connect() as conn:
        return [(UUID(str(r.id)), str(r.audio_path)) for r in (await conn.execute(query)).all()]


async def referenced_paths() -> set[str]:
    query = select(_telecasts.c.audio_path).where(_telecasts.c.audio_path.is_not(None))
    async with get_engine().connect() as conn:
        return {str(r.audio_path) for r in (await conn.execute(query)).all()}


async def mark_expired(ids: list[UUID]) -> None:
    if not ids:
        return
    async with get_engine().begin() as conn:
        await conn.execute(
            update(_telecasts)
            .where(_telecasts.c.id.in_(ids))
            .values(step="expired", audio_path=None, updated_at=utcnow())
        )


async def cleanup_media(
    days: float | None = None, *, dry_run: bool = False, now: datetime | None = None
) -> MediaCleanup:
    settings = get_settings()
    days = settings.press_telecast_retention_days if days is None else days
    report = MediaCleanup(dry_run=dry_run)
    if days <= 0:
        return report
    root = Path(settings.media_dir)
    now = now or utcnow()
    with span("press", "cleanup_media", days=days, dry_run=dry_run) as s:
        rows = await expired_rows(now - timedelta(days=days))
        for _, rel in rows:
            path = root / rel
            report.bytes_freed += _size(path)
            if not dry_run:
                path.unlink(missing_ok=True)
        report.expired = len(rows)
        if not dry_run:
            await mark_expired([tid for tid, _ in rows])
        gone = {rel for _, rel in rows}
        for rel in orphan_files(_media_files(root), await referenced_paths() | gone, now):
            path = root / rel
            report.bytes_freed += _size(path)
            report.orphans += 1
            if not dry_run:
                path.unlink(missing_ok=True)
        s.set(expired=report.expired, orphans=report.orphans, bytes_freed=report.bytes_freed)
    log.info(
        "press.media_cleanup",
        expired=report.expired,
        orphans=report.orphans,
        bytes_freed=report.bytes_freed,
        dry_run=dry_run,
    )
    return report
