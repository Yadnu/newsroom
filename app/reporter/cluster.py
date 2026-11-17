"""Embed new sources and group them into stories by embedding similarity (decision 0010).

Incremental greedy centroid clustering: each unassigned source in the window (oldest first) joins
the most similar recent story if cosine similarity >= threshold, otherwise it starts a new story.
A story's centroid is the normalized mean of its members' embeddings. Already-assigned sources are
never moved, so reruns are idempotent.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import numpy.typing as npt
from sqlalchemy import bindparam, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.archive import span
from app.config import get_settings
from app.db.models import Source, Story, StorySource, utcnow
from app.db.session import get_engine
from app.log import get_logger
from app.shared import llm

Vec = npt.NDArray[np.float64]

EMBED_PAGE = 1000
# Arbitrary constant key for pg_advisory_xact_lock; serializes cluster runs across processes.
_CLUSTER_LOCK_KEY = 0x4E5752_0105

log = get_logger(__name__)

_sources = Source.__table__  # type: ignore[attr-defined]
_stories = Story.__table__  # type: ignore[attr-defined]
_links = StorySource.__table__  # type: ignore[attr-defined]


# ---- pure clustering ----------------------------------------------------------------------


@dataclass(slots=True)
class Cluster:
    story_id: UUID
    title: str
    centroid: Vec
    size: int
    is_new: bool = False
    new_members: list[UUID] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SourceVec:
    id: UUID
    title: str
    embedding: Vec


def unit(v: Any) -> Vec:
    arr = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(arr))
    return arr / n if n > 0 else arr


def assign(
    sources: Sequence[SourceVec], clusters: list[Cluster], threshold: float
) -> list[Cluster]:
    """Greedily assign sources to clusters, creating clusters as needed. Mutates and returns
    ``clusters``; members added this call are in ``new_members``."""
    matrix = np.array([c.centroid for c in clusters]) if clusters else None
    for src in sources:
        v = unit(src.embedding)
        best = -1
        if matrix is not None:
            sims = matrix @ v
            idx = int(np.argmax(sims))
            if sims[idx] >= threshold:
                best = idx
        if best >= 0:
            c = clusters[best]
            c.centroid = unit(c.centroid * c.size + v)
            c.size += 1
            c.new_members.append(src.id)
            assert matrix is not None
            matrix[best] = c.centroid
        else:
            c = Cluster(uuid4(), src.title, v, 1, is_new=True, new_members=[src.id])
            clusters.append(c)
            row = v[np.newaxis, :]
            matrix = row if matrix is None else np.vstack([matrix, row])
    return clusters


# ---- database -----------------------------------------------------------------------------


def embedding_text(title: str, content: str) -> str:
    max_chars = get_settings().reporter_embed_max_chars
    return f"{title}\n\n{content}"[:max_chars]


async def embed_pending_sources(limit: int = 5000) -> int:
    """Embed sources with no embedding yet (not retracted). Returns the number embedded."""
    done = 0
    with span("reporter", "embed_sources") as s:
        engine = get_engine()
        while done < limit:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        select(_sources.c.id, _sources.c.title, _sources.c.content)
                        .where(_sources.c.embedding.is_(None), _sources.c.retracted.is_(False))
                        .order_by(_sources.c.fetched_at)
                        .limit(min(EMBED_PAGE, limit - done))
                    )
                ).all()
            if not rows:
                break
            vectors = await llm.embed(
                [embedding_text(r.title, r.content) for r in rows], "document"
            )
            stmt = (
                update(_sources)
                .where(_sources.c.id == bindparam("b_id"))
                .values(embedding=bindparam("b_emb"))
            )
            async with engine.begin() as conn:
                await conn.execute(
                    stmt, [{"b_id": r.id, "b_emb": v} for r, v in zip(rows, vectors, strict=True)]
                )
            done += len(rows)
        s.set(embedded=done)
    return done


async def cluster_stories(window_hours: int = 24) -> list[Story]:
    """Assign recent, embedded, unassigned sources to stories.

    Returns the stories created or updated by this run.
    """
    threshold = get_settings().reporter_cluster_threshold
    since = utcnow() - timedelta(hours=window_hours)
    seen_at = func.coalesce(_sources.c.published_at, _sources.c.fetched_at)
    with span("reporter", "cluster_stories", window_hours=window_hours, threshold=threshold) as s:
        async with get_engine().begin() as conn:
            await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CLUSTER_LOCK_KEY})
            pending = (
                await conn.execute(
                    select(_sources.c.id, _sources.c.title, _sources.c.embedding)
                    .outerjoin(_links, _links.c.source_id == _sources.c.id)
                    .where(
                        _links.c.source_id.is_(None),
                        _sources.c.embedding.is_not(None),
                        _sources.c.retracted.is_(False),
                        seen_at >= since,
                    )
                    .order_by(seen_at, _sources.c.id)
                )
            ).all()
            if not pending:
                s.set(pending=0, created=0, updated=0)
                return []

            sizes = (
                select(_links.c.story_id, func.count().label("n"))
                .group_by(_links.c.story_id)
                .subquery()
            )
            existing = (
                await conn.execute(
                    select(_stories.c.id, _stories.c.title, _stories.c.centroid, sizes.c.n)
                    .join(sizes, sizes.c.story_id == _stories.c.id)
                    .where(_stories.c.created_at >= since, _stories.c.centroid.is_not(None))
                )
            ).all()
            clusters = [Cluster(r.id, r.title, unit(r.centroid), int(r.n)) for r in existing]
            assign(
                [SourceVec(r.id, r.title, np.asarray(r.embedding)) for r in pending],
                clusters,
                threshold,
            )
            touched = [c for c in clusters if c.new_members]
            created = [c for c in touched if c.is_new]
            updated = [c for c in touched if not c.is_new]

            now = utcnow()
            if created:
                await conn.execute(
                    pg_insert(_stories),
                    [
                        {
                            "id": c.story_id,
                            "title": c.title,
                            "created_at": now,
                            "centroid": c.centroid.tolist(),
                        }
                        for c in created
                    ],
                )
            if updated:
                await conn.execute(
                    update(_stories)
                    .where(_stories.c.id == bindparam("b_id"))
                    .values(centroid=bindparam("b_centroid")),
                    [{"b_id": c.story_id, "b_centroid": c.centroid.tolist()} for c in updated],
                )
            await conn.execute(
                pg_insert(_links).on_conflict_do_nothing(),
                [
                    {"story_id": c.story_id, "source_id": sid}
                    for c in touched
                    for sid in c.new_members
                ],
            )
            s.set(pending=len(pending), created=len(created), updated=len(updated))

    log.info("reporter.cluster", pending=len(pending), created=len(created), updated=len(updated))
    return [
        Story(
            id=c.story_id,
            title=c.title,
            created_at=now,
            centroid=c.centroid.tolist(),
        )
        for c in touched
    ]
