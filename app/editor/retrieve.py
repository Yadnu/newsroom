"""Evidence retrieval: the passages of a claim's cited sources that are closest to the claim.

Only sources the Writer cited (``claim_sources``) and that are not retracted are searched. Each
source is split into overlapping chunks, chunks are embedded as documents and claims as queries
(one batched ``embed()`` call each), and the top-k chunks per claim by cosine similarity are kept.
Chunk vectors are not stored (decision 0012).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import numpy as np
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Source
from app.db.session import get_engine
from app.shared import llm

_sources = Source.__table__  # type: ignore[attr-defined]
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    id: UUID
    outlet: str
    title: str
    content: str
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class ClaimRef:
    """What retrieval needs from a claim: its text and the sources the Writer cited."""

    id: UUID
    text: str
    source_ids: list[UUID]
    line_id: UUID | None = None  # recorded on the judge span so the Archive can find old judgements


@dataclass(frozen=True, slots=True)
class Passage:
    source_id: UUID
    outlet: str
    published_at: datetime | None
    text: str
    similarity: float  # cosine, clipped to 0..1


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Split on whitespace into chunks of at most ``size`` chars, preferring sentence ends.

    Consecutive chunks share about ``overlap`` chars so a fact split across a boundary is still
    whole in one chunk.
    """
    text = " ".join(text.split())
    if not text:
        return []
    if len(text) <= size:
        return [text]
    overlap = min(overlap, size // 2)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max((m.start() for m in _SENTENCE_END.finditer(window)), default=-1)
            if cut <= size // 2:
                cut = window.rfind(" ")
            if cut > 0:
                end = start + cut
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        nxt = end - overlap
        if nxt <= start:
            nxt = end
        # Start the next chunk at a word boundary.
        space = text.find(" ", nxt)
        start = space + 1 if 0 <= space < end else end
    return [c for c in chunks if c]


async def load_sources(ids: Sequence[UUID]) -> dict[UUID, EvidenceSource]:
    """Non-retracted sources by id. Retracted or missing ids are left out."""
    if not ids:
        return {}
    query = select(
        _sources.c.id,
        _sources.c.outlet,
        _sources.c.title,
        _sources.c.content,
        _sources.c.published_at,
    ).where(_sources.c.id.in_(list(set(ids))), _sources.c.retracted.is_(False))
    async with get_engine().connect() as conn:
        rows = (await conn.execute(query)).all()
    return {r.id: EvidenceSource(r.id, r.outlet, r.title, r.content, r.published_at) for r in rows}


def _unit(rows: list[list[float]]) -> np.ndarray:
    m = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    out: np.ndarray = m / norms
    return out


async def retrieve_evidence(claims: Sequence[ClaimRef]) -> dict[UUID, list[Passage]]:
    """Top-k passages per claim from its cited, non-retracted sources. Empty list if none."""
    settings = get_settings()
    result: dict[UUID, list[Passage]] = {c.id: [] for c in claims}
    sources = await load_sources([sid for c in claims for sid in c.source_ids])
    if not sources:
        return result

    chunks: list[tuple[EvidenceSource, str]] = []
    by_source: dict[UUID, list[int]] = {}
    for src in sources.values():
        body = f"{src.title}. {src.content}"[: settings.editor_source_max_chars]
        for piece in chunk_text(body, settings.editor_chunk_chars, settings.editor_chunk_overlap):
            by_source.setdefault(src.id, []).append(len(chunks))
            chunks.append((src, piece))

    todo = [c for c in claims if any(sid in by_source for sid in c.source_ids)]
    if not todo:
        return result
    doc_vecs = _unit(await llm.embed([text for _, text in chunks], "document"))
    query_vecs = _unit(await llm.embed([c.text for c in todo], "query"))

    for claim, qv in zip(todo, query_vecs, strict=True):
        idx = list(dict.fromkeys(i for sid in claim.source_ids for i in by_source.get(sid, [])))
        sims = doc_vecs[idx] @ qv
        order = np.argsort(-sims, kind="stable")[: settings.editor_top_k]
        result[claim.id] = [
            Passage(
                source_id=chunks[idx[j]][0].id,
                outlet=chunks[idx[j]][0].outlet,
                published_at=chunks[idx[j]][0].published_at,
                text=chunks[idx[j]][1],
                similarity=float(min(max(sims[j], 0.0), 1.0)),
            )
            for j in order
        ]
    return result
