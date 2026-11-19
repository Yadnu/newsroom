"""``listen()``: listener audio -> STT (Pipecat) -> utterances -> classified questions (task 5.1).

Pipeline: STT service -> ``_Heard`` (collects transcripts). A feeder task pushes the audio as
``InputAudioRawFrame``s between a VAD started/stopped pair (the stop asks Deepgram to finalize).

An utterance ends when no new final transcript has arrived for ``caller_utterance_gap_ms``, when the
audio ends (push-to-talk released; we then wait ``caller_finalize_wait_ms`` for the last words),
or at ``caller_max_question_s`` of audio. Raw audio is never stored or logged.
"""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from pipecat.frames.frames import (
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.stt_service import STTService
from pipecat.workers.runner import WorkerRunner

from app.archive import span
from app.caller.intent import classify
from app.caller.stt import make_stt
from app.caller.types import CallerContext, CallerEvent, CallerQuestion, Intent, Interim
from app.config import Settings, get_settings

Classifier = Callable[[str, CallerContext], Awaitable[Intent]]
STT_CONNECT_WAIT_S = 5.0
SETTLE_S = 0.3  # after release, once a final transcript is in, how long to wait for a straggler


async def stt_ready(stt: STTService) -> None:
    """Wait until a streaming STT has its socket open. Pipecat's Deepgram service silently drops
    audio sent before that, which cut the first word of a question; it exposes no public event
    for it, so this waits on its ``_connection_settled`` event when the service has one."""
    settled = getattr(stt, "_connection_settled", None)
    if isinstance(settled, asyncio.Event):
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(settled.wait(), STT_CONNECT_WAIT_S)


class _Heard(FrameProcessor):
    """End of the pipeline: forwards transcripts to ``listen()`` through a queue."""

    def __init__(self, out: "asyncio.Queue[tuple[str, str]]") -> None:
        super().__init__(name="caller-heard")
        self.out = out

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            if frame.text.strip():
                self.out.put_nowait(("final", frame.text.strip()))
        elif isinstance(frame, InterimTranscriptionFrame):
            if frame.text.strip():
                self.out.put_nowait(("interim", frame.text.strip()))
        else:
            await self.push_frame(frame, direction)


async def listen(
    audio: AsyncIterator[bytes],
    context: CallerContext,
    *,
    stt: STTService | None = None,
    settings: Settings | None = None,
    classifier: Classifier | None = None,
) -> AsyncIterator[CallerEvent]:
    """Yield ``Interim`` while the listener talks and a ``CallerQuestion`` per utterance.
    ``audio`` is PCM16 mono at ``caller_sample_rate``."""
    settings = settings or get_settings()
    stt = stt or make_stt(settings)
    classifier = classifier or classify
    sr = settings.caller_sample_rate
    max_bytes = settings.caller_max_question_s * sr * 2
    gap_s = settings.caller_utterance_gap_ms / 1000
    finalize_s = settings.caller_finalize_wait_ms / 1000

    heard: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    worker = PipelineWorker(
        Pipeline([stt, _Heard(heard)]),
        params=PipelineParams(audio_in_sample_rate=sr),
        idle_timeout_secs=None,
        enable_rtvi=False,
        enable_turn_tracking=False,
        check_dangling_tasks=False,
    )
    runner = WorkerRunner(handle_sigint=False, check_dangling_tasks=False)
    await runner.add_workers(worker)
    running = asyncio.create_task(runner.run())
    stats: dict[str, Any] = {"audio_ms": 0, "questions": 0, "interims": 0, "capped": False}

    async def feed() -> None:
        sent = 0
        try:
            await stt_ready(stt)
            await worker.queue_frame(VADUserStartedSpeakingFrame())
            async for chunk in audio:
                if not chunk:
                    continue
                if sent + len(chunk) > max_bytes:
                    chunk = chunk[: max_bytes - sent]
                    stats["capped"] = True
                sent += len(chunk)
                if chunk:
                    await worker.queue_frame(
                        InputAudioRawFrame(audio=chunk, sample_rate=sr, num_channels=1)
                    )
                if stats["capped"]:
                    break
            await worker.queue_frame(VADUserStoppedSpeakingFrame())
        finally:
            stats["audio_ms"] = sent * 1000 // (sr * 2)
            heard.put_nowait(("audio_done", ""))

    feeder = asyncio.create_task(feed())
    finals: list[str] = []
    pending = ""  # latest interim words after the last final
    audio_done = False
    first_word_at: float | None = None

    async def question() -> CallerQuestion:
        transcript = " ".join([*finals, pending] if pending else finals).strip()
        with span(
            "caller",
            "question",
            context.briefing_id,
            transcript=transcript,
            stt_ms=round((time.perf_counter() - (first_word_at or time.perf_counter())) * 1000),
        ) as s:
            intent = await classifier(transcript, context)
            s.set(intent=intent.intent, story_id=intent.story_id)
        stats["questions"] += 1
        return CallerQuestion(transcript, intent.intent, intent.story_id, intent.restated)

    with span("caller", "listen", context.briefing_id) as s:
        try:
            while True:
                if audio_done and finals and not pending:
                    timeout: float | None = min(SETTLE_S, finalize_s)  # last words are in
                elif audio_done:
                    timeout = finalize_s
                elif finals and not pending:
                    timeout = gap_s
                else:
                    timeout = None
                try:
                    kind, text = await asyncio.wait_for(heard.get(), timeout)
                except TimeoutError:
                    if finals or pending:
                        yield await question()
                        finals, pending, first_word_at = [], "", None
                    if audio_done:
                        break
                    continue
                if kind == "audio_done":
                    audio_done = True
                    if not finals and not pending and heard.empty():
                        # Nothing heard yet: still give the STT its finalize window.
                        continue
                elif kind == "interim":
                    first_word_at = first_word_at or time.perf_counter()
                    pending = text
                    stats["interims"] += 1
                    yield Interim(" ".join([*finals, text]))
                elif kind == "final":
                    first_word_at = first_word_at or time.perf_counter()
                    finals.append(text)
                    pending = ""
                    yield Interim(" ".join(finals))
        finally:
            feeder.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await feeder
            try:
                await worker.queue_frame(EndFrame())
                await asyncio.wait_for(asyncio.shield(running), 10)
            except asyncio.CancelledError:
                with contextlib.suppress(BaseException):
                    await asyncio.wait_for(worker.cancel(), 5)
                running.cancel()
                raise
            except Exception:
                await worker.cancel()
                running.cancel()
            s.set(**stats)
