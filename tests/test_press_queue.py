"""Telecast jobs on the ARQ worker with an in-process fallback (task 9.3). No Redis needed."""

from typing import Any
from uuid import UUID, uuid4

import pytest

import app.press.queue as queue
import app.press.telecast as tc
from app import worker
from app.config import Settings

TID, SID = uuid4(), uuid4()


@pytest.fixture(autouse=True)
def fresh_queue() -> Any:
    queue.reset()
    yield
    queue.reset()


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    seen: dict[str, list[Any]] = {"enqueued": [], "scheduled": [], "set": []}

    def schedule(t: UUID, s: UUID) -> None:
        seen["scheduled"].append((t, s))

    async def record(t: UUID, **values: object) -> None:
        seen["set"].append(values)

    monkeypatch.setattr(tc, "schedule", schedule)
    monkeypatch.setattr(tc, "_set", record)
    return seen


def _mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setattr(
        tc, "get_settings", lambda: Settings(_env_file=None, press_telecast_runner=mode)
    )


def _enqueue(monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]], ok: bool) -> None:
    async def enqueue(t: UUID, s: UUID, *, need_worker: bool = True) -> bool:
        calls["enqueued"].append((t, s, need_worker))
        return ok

    monkeypatch.setattr(queue, "enqueue_telecast", enqueue)


async def test_auto_queues_for_the_worker(monkeypatch: pytest.MonkeyPatch, calls: Any) -> None:
    _mode(monkeypatch, "auto")
    _enqueue(monkeypatch, calls, ok=True)
    await tc.dispatch(TID, SID)
    assert calls["enqueued"] == [(TID, SID, True)] and calls["scheduled"] == []


async def test_auto_falls_back_to_this_process(monkeypatch: pytest.MonkeyPatch, calls: Any) -> None:
    _mode(monkeypatch, "auto")
    _enqueue(monkeypatch, calls, ok=False)
    await tc.dispatch(TID, SID)
    assert calls["scheduled"] == [(TID, SID)]


async def test_worker_only_fails_the_telecast_without_redis(
    monkeypatch: pytest.MonkeyPatch, calls: Any
) -> None:
    _mode(monkeypatch, "worker")
    _enqueue(monkeypatch, calls, ok=False)
    await tc.dispatch(TID, SID)
    assert calls["enqueued"] == [(TID, SID, False)]  # queued even before a worker checks in
    assert calls["scheduled"] == []
    assert calls["set"] == [{"step": "failed", "error": "queued: the worker queue is unavailable"}]


async def test_inprocess_never_touches_redis(monkeypatch: pytest.MonkeyPatch, calls: Any) -> None:
    _mode(monkeypatch, "inprocess")
    _enqueue(monkeypatch, calls, ok=True)
    await tc.dispatch(TID, SID)
    assert calls["enqueued"] == [] and calls["scheduled"] == [(TID, SID)]


async def test_an_unreachable_redis_is_tried_once_a_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[Any] = []

    async def down(settings: Any) -> Any:
        attempts.append(settings)
        raise ConnectionError("refused")

    monkeypatch.setattr(queue, "create_pool", down)
    assert await queue.enqueue_telecast(TID, SID) is False
    assert await queue.enqueue_telecast(TID, SID) is False
    assert len(attempts) == 1  # remembered
    assert attempts[0].conn_timeout == 1 and attempts[0].conn_retries == 0


async def test_enqueue_names_the_job_after_the_telecast(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs: list[tuple[Any, ...]] = []

    alive = {"worker": True}

    class Pool:
        async def exists(self, key: str) -> int:
            assert key == "arq:queue:health-check"
            return int(alive["worker"])

        async def enqueue_job(self, name: str, *args: Any, _job_id: str) -> object:
            jobs.append((name, *args, _job_id))
            return object()

        async def aclose(self) -> None:
            return None

    async def up(settings: Any) -> Pool:
        return Pool()

    monkeypatch.setattr(queue, "create_pool", up)
    assert await queue.enqueue_telecast(TID, SID) is True
    assert jobs == [("telecast_job", str(TID), str(SID), f"telecast:{TID}")]
    alive["worker"] = False  # Redis up, no worker: auto runs it here instead
    assert await queue.enqueue_telecast(TID, SID) is False
    assert await queue.enqueue_telecast(TID, SID, need_worker=False) is True  # worker mode
    assert len(jobs) == 2
    await queue.close_pool()


async def test_worker_job_runs_the_telecast(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[tuple[UUID, UUID]] = []

    async def run(t: UUID, s: UUID) -> None:
        ran.append((t, s))

    monkeypatch.setattr(worker, "run_telecast", run)
    assert await worker.telecast_job({}, str(TID), str(SID)) == str(TID)
    assert ran == [(TID, SID)]
    (job,) = [
        f for f in worker.WorkerSettings.functions if getattr(f, "name", "") == "telecast_job"
    ]
    assert job.timeout_s == 900 and job.max_tries == 1
    assert worker.WorkerSettings.health_check_interval == queue.WORKER_HEALTH_S
