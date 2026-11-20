"""``speak()``: voice a ``ClearedScript`` through a Pipecat pipeline (task 4.2, decision 0017).

Pipeline: TTS service -> ``_Airing``. ``speak()`` feeds one line at a time and waits for that line's
``TTSStoppedFrame``, so line boundaries are exact. ``_Airing`` timestamps lines on the audio clock
(samples sent / sample rate), paces realtime sessions to it, and drops audio while paused.

Barge-in: ``session.pause()`` cuts the current line (queued audio is dropped and the TTS gets an
interruption); ``resume()`` replays that line from its start.
"""

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pipecat.frames.frames import (
    EndFrame,
    Frame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.tts_service import TTSService
from pipecat.workers.runner import WorkerRunner
from sqlalchemy import text

from app.anchor.session import VoiceSession
from app.anchor.tts import make_tts
from app.archive import span
from app.config import Settings, get_settings
from app.db.models import BriefingStatus
from app.db.session import get_engine
from app.log import get_logger
from app.standards_desk import ClearedLine, ClearedScript

SLICE_MS = 20  # pacing granularity; bounds how late a pause can take effect

log = get_logger(__name__)


class AnchorError(RuntimeError):
    """The TTS did not finish a line in time."""


@dataclass(frozen=True, slots=True)
class LineTiming:
    line_id: UUID
    order: int
    start_ms: int
    end_ms: int


@dataclass(slots=True)
class SpeakReport:
    briefing_id: UUID
    lines: list[LineTiming] = field(default_factory=list)
    audio_ms: int = 0
    pauses: int = 0
    answers: int = 0  # listener questions answered on air (task 5.3)
    completed: bool = False


class _Airing(FrameProcessor):
    """End of the pipeline: forwards the current line's audio to the session on the audio clock."""

    def __init__(self, session: VoiceSession, sample_rate: int, send_ahead_ms: int) -> None:
        super().__init__(name="anchor-airing")
        self.session = session
        self.sample_rate = sample_rate
        self.send_ahead_s = send_ahead_ms / 1000
        self.samples = 0  # audio clock
        self._wall0: float | None = None
        self._line: ClearedLine | None = None
        self._ctx: str | None = None
        self._done: asyncio.Future[bool] | None = None
        self.line_start_ms: int | None = None
        self._extra: dict[str, Any] = {"kind": "script"}
        self.last_audio_at: float | None = None  # perf_counter of the last chunk sent

    @property
    def clock_ms(self) -> int:
        return self.samples * 1000 // self.sample_rate

    def expect(
        self, line: ClearedLine, extra: dict[str, Any] | None = None
    ) -> asyncio.Future[bool]:
        """Arm for one line. The future is True when it played out, False if interrupted.
        ``extra`` is added to the line's ``line`` event (``kind``, ``question_id``)."""
        self._line, self._ctx, self.line_start_ms = line, None, None
        self._extra = extra or {"kind": "script"}
        self._done = asyncio.get_running_loop().create_future()
        return self._done

    def _finish(self, played: bool) -> None:
        if self._done is not None and not self._done.done():
            self._done.set_result(played)
        self._line, self._ctx = None, None

    async def interrupt(self) -> None:
        self._finish(False)
        await self.broadcast_interruption()  # type: ignore[no-untyped-call]

    def restart_clock(self) -> None:
        """After a pause, pace from now again (the clock itself keeps counting)."""
        self._wall0 = time.perf_counter() - self.clock_ms / 1000

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSStartedFrame):
            if self._line is not None and self._ctx is None:
                self._ctx = frame.context_id
        elif isinstance(frame, TTSAudioRawFrame):
            if self._line is None or frame.context_id != self._ctx or self.session.paused:
                return  # stale audio from an interrupted line, or paused
            if frame.sample_rate != self.sample_rate:
                log.warning("anchor.sample_rate_mismatch", got=frame.sample_rate)
            if self.line_start_ms is None:
                self.line_start_ms = self.clock_ms
                await self.session.send_event(
                    {
                        "type": "line",
                        "line_id": str(self._line.id),
                        "order": self._line.order,
                        "text": self._line.text,
                        "start_ms": self.line_start_ms,
                        **self._extra,
                    }
                )
            await self.play(frame.audio)
        elif isinstance(frame, TTSStoppedFrame):
            if self._ctx is not None and frame.context_id == self._ctx:
                self._finish(True)
        else:
            await self.push_frame(frame, direction)

    async def play(self, pcm: bytes) -> None:
        """Send PCM in ``SLICE_MS`` slices, paced to the audio clock for realtime sessions."""
        step = self.sample_rate * SLICE_MS // 1000 * 2
        for i in range(0, len(pcm), step):
            if self.session.paused:
                return
            if self.session.realtime:
                if self._wall0 is None:
                    self._wall0 = time.perf_counter()
                due = self._wall0 + self.clock_ms / 1000 - self.send_ahead_s
                delay = due - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
                if self.session.paused:
                    return
            chunk = pcm[i : i + step]
            await self.session.send_audio(chunk)
            self.samples += len(chunk) // 2
            self.last_audio_at = time.perf_counter()

    async def silence(self, ms: int) -> None:
        await self.play(b"\x00" * (self.sample_rate * ms // 1000 * 2))


async def speak(
    script: ClearedScript,
    session: VoiceSession,
    *,
    tts: TTSService | None = None,
    settings: Settings | None = None,
) -> SpeakReport:
    """Voice every cleared line in order, write per-line audio timestamps, and mark the briefing
    ``aired`` when the last line has played. Only a ``ClearedScript`` is accepted."""
    if not isinstance(script, ClearedScript):
        raise TypeError("the Anchor speaks only a ClearedScript (standards_desk.clear_for_air)")
    settings = settings or get_settings()
    tts = tts or make_tts(settings)
    sr = settings.anchor_sample_rate
    report = SpeakReport(briefing_id=script.briefing_id)
    airing = _Airing(session, sr, settings.anchor_send_ahead_ms)

    async def on_pause() -> None:
        await airing.interrupt()
        await session.send_event({"type": "paused", "at_ms": airing.clock_ms})

    async def on_resume() -> None:
        airing.restart_clock()
        await session.send_event({"type": "resumed", "at_ms": airing.clock_ms})

    session.on_pause(on_pause)
    session.on_resume(on_resume)

    worker = PipelineWorker(
        Pipeline([tts, airing]),
        params=PipelineParams(audio_out_sample_rate=sr),
        idle_timeout_secs=None,
        enable_rtvi=False,
        enable_turn_tracking=False,
        check_dangling_tasks=False,
    )
    runner = WorkerRunner(handle_sigint=False, check_dangling_tasks=False)
    await runner.add_workers(worker)
    running = asyncio.create_task(runner.run())

    adapter = type(tts).__name__
    with span("anchor", "speak", script.briefing_id, lines=len(script.lines), adapter=adapter) as s:
        try:
            await session.send_event(
                {
                    "type": "start",
                    "briefing_id": str(script.briefing_id),
                    "sample_rate": sr,
                    "lines": len(script.lines),
                }
            )

            async def say(line: ClearedLine, extra: dict[str, Any]) -> LineTiming | None:
                """Speak one line; ``None`` if a pause cut it (the caller replays it)."""
                with span("anchor", "line", line_id=line.id, order=line.order, **extra) as ls:
                    played = airing.expect(line, extra)
                    await worker.queue_frame(TTSSpeakFrame(line.text))
                    timeout = settings.anchor_line_timeout_s + len(line.text) / 10
                    try:
                        ok = await asyncio.wait_for(played, timeout)
                    except TimeoutError as e:
                        raise AnchorError(f"TTS gave no end for line {line.order}") from e
                    if not ok:
                        ls.set(interrupted=True)
                        return None
                    start = airing.line_start_ms
                    timing = LineTiming(
                        line.id,
                        line.order,
                        start if start is not None else airing.clock_ms,
                        airing.clock_ms,
                    )
                    report.lines.append(timing)
                    ls.set(start_ms=timing.start_ms, end_ms=timing.end_ms, chars=len(line.text))
                await session.send_event(
                    {"type": "line_end", "line_id": str(line.id), "end_ms": timing.end_ms, **extra}
                )
                return timing

            async def answer_if_queued() -> bool:
                """Speak a queued answer (task 5.3) before going on with the briefing."""
                item = session.take_interjection()
                if item is None:
                    return False
                answer, question_id = item
                extra = {"kind": "answer", "question_id": question_id}
                j = 0
                while j < len(answer.lines):
                    await session.wait_unpaused()
                    if await say(answer.lines[j], extra) is None:
                        continue  # paused mid-answer: replay that line
                    j += 1
                    await airing.silence(settings.anchor_line_gap_ms)
                report.answers += 1
                return True

            i = 0
            while i < len(script.lines):
                await session.wait_unpaused()
                if await answer_if_queued():
                    continue
                if await say(script.lines[i], {"kind": "script"}) is None:
                    continue  # paused mid-line: replay it after resume
                i += 1
                if i < len(script.lines):
                    await airing.silence(settings.anchor_line_gap_ms)
            while await answer_if_queued():  # a question asked during the last line
                pass
            report.completed = True
        finally:
            report.audio_ms = airing.clock_ms
            report.pauses = session.pauses
            s.set(
                spoken=len(report.lines),
                audio_ms=report.audio_ms,
                pauses=report.pauses,
                answers=report.answers,
                completed=report.completed,
                chars=sum(len(ln.text) for ln in script.lines),
            )
            await _shutdown(worker, running)
            try:
                await session.send_event(
                    {"type": "done", "audio_ms": report.audio_ms, "completed": report.completed}
                )
            except Exception as e:  # the listener may already be gone
                log.info("anchor.done_not_sent", error=type(e).__name__)
            await session.close()
            if report.lines:
                await store_timings(script.briefing_id, report.lines, aired=report.completed)
    return report


async def _shutdown(worker: PipelineWorker, running: "asyncio.Task[Any]") -> None:
    try:
        await worker.queue_frame(EndFrame())
        await asyncio.wait_for(asyncio.shield(running), 10)
    except asyncio.CancelledError:  # we were cancelled: still stop Pipecat's tasks, then re-raise
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(worker.cancel(), 5)
        running.cancel()
        raise
    except Exception:
        await worker.cancel()
        running.cancel()


async def store_timings(briefing_id: UUID, timings: list[LineTiming], aired: bool) -> None:
    async with get_engine().begin() as conn:
        for t in timings:
            await conn.execute(
                text(
                    "UPDATE script_lines SET audio_start_ms = :s, audio_end_ms = :e WHERE id = :i"
                ),
                {"s": t.start_ms, "e": t.end_ms, "i": t.line_id},
            )
        if aired:
            await conn.execute(
                text("UPDATE briefings SET status = :st WHERE id = :b"),
                {"st": BriefingStatus.aired.value, "b": briefing_id},
            )
