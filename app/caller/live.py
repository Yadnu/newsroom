"""Push-to-talk over the Anchor WebSocket (task 5.1, decision 0018).

Client -> server: ``{"type": "mic_start", "sample_rate": 16000}``, binary PCM16 mono chunks,
``{"type": "mic_end"}``. Server -> client: ``caller_interim{text}``, ``caller_error{message}``,
``caller_question{id, transcript, intent, story_id, story_title, restated}``.

One question at a time. Mic audio outside a mic_start/mic_end pair is dropped. Audio is never
stored.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID

from app.caller.context import context_for
from app.caller.pipeline import listen
from app.caller.types import CallerConfigError, CallerContext, CallerQuestion, Interim
from app.config import Settings, get_settings
from app.log import get_logger
from app.standards_desk import ClearedScript

QUEUE_CHUNKS = 400  # ~12 s of 30 ms chunks buffered before frames are dropped

Send = Callable[[dict[str, Any]], Awaitable[None]]
Listener = Callable[..., AsyncIterator[Any]]

log = get_logger(__name__)


class CallIn:
    def __init__(
        self,
        script: ClearedScript,
        send: Send,
        current_line: Callable[[], UUID | None],
        *,
        settings: Settings | None = None,
        listener: Listener | None = None,
    ) -> None:
        self.script = script
        self.send = send
        self.current_line = current_line
        self.settings = settings or get_settings()
        self.listener = listener or listen
        self._context: CallerContext | None = None
        self._queue: asyncio.Queue[bytes | None] | None = None
        self._task: asyncio.Task[None] | None = None
        self.dropped = 0

    @property
    def active(self) -> bool:
        return self._queue is not None

    def _story_of_line(self, line_id: UUID | None) -> UUID | None:
        return next((ln.story_id for ln in self.script.lines if ln.id == line_id), None)

    async def start(self, sample_rate: int | None = None) -> None:
        if self.active or (self._task is not None and not self._task.done()):
            return  # one question at a time
        if sample_rate is not None and sample_rate != self.settings.caller_sample_rate:
            await self.send(
                {
                    "type": "caller_error",
                    "message": f"mic must send {self.settings.caller_sample_rate} Hz PCM16",
                }
            )
            return
        if self._context is None:
            self._context = await context_for(self.script)
        context = CallerContext(
            self._context.briefing_id,
            self._context.stories,
            self._story_of_line(self.current_line()),
        )
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(QUEUE_CHUNKS)
        self._queue = queue
        self._task = asyncio.create_task(self._run(queue, context))

    def audio(self, chunk: bytes) -> None:
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(chunk)
        except asyncio.QueueFull:
            self.dropped += 1

    async def end(self) -> None:
        queue, self._queue = self._queue, None
        if queue is not None:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)

    async def wait(self, seconds: float) -> None:
        """Let a question in flight finish, for at most ``seconds``."""
        if self._task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.shield(self._task), seconds)

    async def close(self) -> None:
        await self.end()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def _run(self, queue: "asyncio.Queue[bytes | None]", context: CallerContext) -> None:
        async def chunks() -> AsyncIterator[bytes]:
            while (chunk := await queue.get()) is not None:
                yield chunk

        titles = {s.id: s.title for s in context.stories}
        try:
            async for event in self.listener(chunks(), context, settings=self.settings):
                if isinstance(event, Interim):
                    await self.send({"type": "caller_interim", "text": event.text})
                elif isinstance(event, CallerQuestion):
                    await self.send(
                        {
                            "type": "caller_question",
                            "id": str(event.id),
                            "transcript": event.transcript,
                            "intent": event.intent,
                            "story_id": str(event.story_id) if event.story_id else None,
                            "story_title": titles.get(event.story_id) if event.story_id else None,
                            "restated": event.restated,
                            "allowed": event.screen.allowed if event.screen else True,
                            "screen_category": event.screen.category if event.screen else "ok",
                            "screen_reason": event.screen.reason if event.screen else "",
                        }
                    )
        except CallerConfigError as e:
            log.warning("caller.not_configured", error=str(e))
            await self.send({"type": "caller_error", "message": "speech-to-text is not configured"})
        except Exception as e:
            log.warning("caller.failed", error=type(e).__name__)
            with contextlib.suppress(Exception):
                await self.send(
                    {"type": "caller_error", "message": "could not process the question"}
                )
        finally:
            if self._queue is queue:
                self._queue = None
