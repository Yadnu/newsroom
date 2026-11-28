"""Push-to-talk over the Anchor WebSocket (task 5.1, decision 0018).

Client -> server: ``{"type": "mic_start", "sample_rate": 16000}``, binary PCM16 mono chunks,
``{"type": "mic_end"}``. Server -> client: ``caller_interim{text}``, ``caller_error{message}``,
``caller_question{id, transcript, intent, story_id, story_title, restated}``. A typed question
(task 9.6) is ``{"type": "ask", "text": "..."}`` through ``CallIn.ask``.

One question at a time. Mic audio outside a mic_start/mic_end pair is dropped. Audio is never
stored.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID

from app.caller.ask import clean_typed, question_from_text
from app.caller.context import context_for
from app.caller.pipeline import listen
from app.caller.types import CallerConfigError, CallerContext, CallerQuestion, Interim
from app.config import Settings, get_settings
from app.log import get_logger
from app.standards_desk import ClearedScript

QUEUE_CHUNKS = 400  # ~12 s of 30 ms chunks buffered before frames are dropped

Send = Callable[[dict[str, Any]], Awaitable[None]]
Listener = Callable[..., AsyncIterator[Any]]
Asker = Callable[[str, CallerContext], Awaitable[CallerQuestion]]
OnQuestion = Callable[[CallerQuestion], Awaitable[None]]

log = get_logger(__name__)


def question_event(q: CallerQuestion, titles: dict[UUID, str]) -> dict[str, Any]:
    """The ``caller_question`` event for a classified, screened question (spoken or typed)."""
    return {
        "type": "caller_question",
        "id": str(q.id),
        "transcript": q.transcript,
        "intent": q.intent,
        "story_id": str(q.story_id) if q.story_id else None,
        "story_title": titles.get(q.story_id) if q.story_id else None,
        "restated": q.restated,
        "allowed": q.screen.allowed if q.screen else True,
        "screen_category": q.screen.category if q.screen else "ok",
        "screen_reason": q.screen.reason if q.screen else "",
    }


class CallIn:
    def __init__(
        self,
        script: ClearedScript,
        send: Send,
        current_line: Callable[[], UUID | None],
        *,
        settings: Settings | None = None,
        listener: Listener | None = None,
        asker: Asker | None = None,
        on_question: OnQuestion | None = None,
        default_story: UUID | None = None,
    ) -> None:
        self.script = script
        self.send = send
        self.current_line = current_line
        self.settings = settings or get_settings()
        self.listener = listener or listen
        self.asker = asker or question_from_text
        self.on_question = on_question  # the Producer answers here (task 5.3)
        self.default_story = default_story  # current story when no line is playing (telecasts)
        self._context: CallerContext | None = None
        self._queue: asyncio.Queue[bytes | None] | None = None
        self._task: asyncio.Task[None] | None = None
        self.dropped = 0

    @property
    def active(self) -> bool:
        return self._queue is not None

    def _story_of_line(self, line_id: UUID | None) -> UUID | None:
        return next((ln.story_id for ln in self.script.lines if ln.id == line_id), None)

    @property
    def busy(self) -> bool:
        """A question is being heard or answered."""
        return self.active or (self._task is not None and not self._task.done())

    async def context(self) -> CallerContext:
        """The briefing's stories (loaded once) and the story of the line being read now."""
        if self._context is None:
            self._context = await context_for(self.script)
        return CallerContext(
            self._context.briefing_id,
            self._context.stories,
            self._story_of_line(self.current_line()) or self.default_story,
        )

    async def start(self, sample_rate: int | None = None) -> None:
        if self.busy:
            return  # one question at a time
        if sample_rate is not None and sample_rate != self.settings.caller_sample_rate:
            await self.send(
                {
                    "type": "caller_error",
                    "message": f"mic must send {self.settings.caller_sample_rate} Hz PCM16",
                }
            )
            return
        context = await self.context()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(QUEUE_CHUNKS)
        self._queue = queue
        self._task = asyncio.create_task(self._run(queue, context))

    async def ask(self, text: str) -> None:
        """A typed question (task 9.6): classified, screened and handed on like a spoken one."""
        if self.busy:
            await self.send({"type": "caller_error", "message": "one question at a time"})
            return
        if not clean_typed(text):
            return
        context = await self.context()
        self._task = asyncio.create_task(self._typed(text, context))

    async def _typed(self, text: str, context: CallerContext) -> None:
        titles = {s.id: s.title for s in context.stories}
        try:
            question = await self.asker(text, context)
            await self.send(question_event(question, titles))
            if self.on_question is not None:
                await self.on_question(question)
        except Exception as e:
            log.warning("caller.typed_failed", error=type(e).__name__)
            with contextlib.suppress(Exception):
                await self.send(
                    {"type": "caller_error", "message": "could not process the question"}
                )

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
        asked = 0
        try:
            async for event in self.listener(chunks(), context, settings=self.settings):
                if isinstance(event, Interim):
                    await self.send({"type": "caller_interim", "text": event.text})
                elif isinstance(event, CallerQuestion):
                    asked += 1
                    await self.send(question_event(event, titles))
                    if self.on_question is not None:
                        await self.on_question(event)
            if not asked:  # released without a word heard: say so, or the client waits forever
                await self.send({"type": "caller_error", "message": "did not catch a question"})
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
