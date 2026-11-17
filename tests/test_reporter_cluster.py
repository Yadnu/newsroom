import random
from typing import Any
from uuid import uuid4

import numpy as np
import pytest

import app.worker as worker
from app.db.models import EMBEDDING_DIM
from app.reporter.cluster import Cluster, SourceVec, assign, embedding_text, unit
from app.reporter.ingest import IngestReport
from app.shared.llm import LLMConfigError


def axis(i: int, noise: float = 0.0, seed: int = 0) -> np.ndarray:
    v = np.zeros(EMBEDDING_DIM)
    v[i] = 1.0
    if noise:
        rng = random.Random(seed)  # stdlib: numpy.random's DLL is blocked on some Windows hosts
        v += np.array([rng.gauss(0, noise) for _ in range(EMBEDDING_DIM)])
    return unit(v)


def src(i: int, noise: float = 0.0, seed: int = 0, title: str = "t") -> SourceVec:
    return SourceVec(uuid4(), title, axis(i, noise, seed))


def test_similar_sources_share_a_story_and_distinct_ones_do_not() -> None:
    a1, a2, b1 = src(0, 0.005, 1, "Chip A"), src(0, 0.005, 2, "Chip B"), src(1, title="Rules")
    clusters = assign([a1, a2, b1], [], threshold=0.8)
    assert len(clusters) == 2
    chip, rules = clusters
    assert chip.new_members == [a1.id, a2.id] and chip.size == 2 and chip.is_new
    assert chip.title == "Chip A"  # first (oldest) source names the story
    assert rules.new_members == [b1.id]
    assert np.linalg.norm(chip.centroid) == pytest.approx(1.0)


def test_source_joins_existing_story_and_moves_centroid() -> None:
    sid = uuid4()
    existing = Cluster(sid, "Old story", axis(0), size=3)
    s = SourceVec(uuid4(), "new", unit(axis(0) * 4 + axis(1)))  # sim ~0.97 with axis 0
    (c,) = assign([s], [existing], threshold=0.8)
    assert c.story_id == sid and not c.is_new
    assert c.new_members == [s.id] and c.size == 4
    expected = unit(axis(0) * 3 + unit(axis(0) * 4 + axis(1)))
    assert np.allclose(c.centroid, expected)


def test_threshold_is_inclusive_and_strict_below() -> None:
    base = axis(0)
    angle = np.arccos(0.8)
    at = unit(np.cos(angle) * axis(0) + np.sin(angle) * axis(1))
    assert float(at @ base) == pytest.approx(0.8)
    joined = assign([SourceVec(uuid4(), "x", at)], [Cluster(uuid4(), "s", base, 1)], 0.8 - 1e-9)
    assert len(joined) == 1
    split = assign([SourceVec(uuid4(), "x", at)], [Cluster(uuid4(), "s", base, 1)], 0.8 + 1e-6)
    assert len(split) == 2


def test_picks_the_most_similar_story() -> None:
    near, far = Cluster(uuid4(), "near", axis(0), 1), Cluster(uuid4(), "far", axis(1), 1)
    s = SourceVec(uuid4(), "x", unit(axis(0) * 3 + axis(1)))
    assign([s], [far, near], threshold=0.5)
    assert near.new_members == [s.id] and far.new_members == []


def test_no_sources_changes_nothing() -> None:
    c = Cluster(uuid4(), "s", axis(0), 2)
    assert assign([], [c], 0.8) == [c] and c.new_members == []


def test_embedding_text_is_capped() -> None:
    assert embedding_text("Title", "x" * 50_000) == ("Title\n\n" + "x" * 50_000)[:8000]


# ---- worker job ---------------------------------------------------------------------------


async def test_ingest_job_runs_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def ingest(*_a: Any, **_k: Any) -> IngestReport:
        calls.append("ingest")
        return IngestReport(new_sources=4)

    async def embed(*_a: Any, **_k: Any) -> int:
        calls.append("embed")
        return 4

    async def cluster(window_hours: int) -> list[object]:
        calls.append(f"cluster:{window_hours}")
        return [object(), object()]

    monkeypatch.setattr(worker, "ingest_feeds", ingest)
    monkeypatch.setattr(worker, "embed_pending_sources", embed)
    monkeypatch.setattr(worker, "cluster_stories", cluster)
    result = await worker.ingest_job({})
    assert calls == ["ingest", "embed", "cluster:24"]
    assert result["ingest"]["new_sources"] == 4
    assert (result["embedded"], result["stories_touched"]) == (4, 2)


async def test_ingest_job_skips_embedding_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ingest(*_a: Any, **_k: Any) -> IngestReport:
        return IngestReport()

    async def embed(*_a: Any, **_k: Any) -> int:
        raise LLMConfigError("NEWSROOM_VOYAGE_API_KEY is not set")

    async def cluster(window_hours: int) -> list[object]:
        return []

    monkeypatch.setattr(worker, "ingest_feeds", ingest)
    monkeypatch.setattr(worker, "embed_pending_sources", embed)
    monkeypatch.setattr(worker, "cluster_stories", cluster)
    result = await worker.ingest_job({})
    assert result["embedded"] == 0
