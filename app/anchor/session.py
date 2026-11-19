"""Where the Anchor's audio goes. A ``VoiceSession`` gets PCM16 mono chunks and JSON events, and
owns ``pause()`` / ``resume()`` for barge-in.

Events (also the WebSocket protocol for the web Player, decision 0017):
``{"type": "start", "briefing_id", "sample_rate", "lines"}``,
``{"type": "line", "line_id", "order", "text", "start_ms"}``,
``{"type": "line_end", "line_id", "end_ms"}``, ``{"type": "paused", "at_ms"}``,
``{"type": "resumed", "at_ms"}``, ``{"type": "done", "audio_ms", "completed"}``.
"""

import asyncio
import wave
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from starlette.websockets import WebSocket


class VoiceSession:
    """Base sink. ``realtime`` sessions are paced to the audio clock (a listener hears them);
    others take audio as fast as the TTS makes it."""

    realtime = False

    def __init__(self) -> None:
        self._unpaused = asyncio.Event()
        self._unpaused.set()
        self._on_pause: list[Callable[[], Awaitable[None]]] = []
        self._on_resume: list[Callable[[], Awaitable[None]]] = []
        self._interjections: deque[tuple[Any, str]] = deque()
        self.pauses = 0

    # ---- sink ------------------------------------------------------------------------------

    async def send_audio(self, pcm: bytes) -> None:
        raise NotImplementedError

    async def send_event(self, event: dict[str, Any]) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        return None

    # ---- barge-in --------------------------------------------------------------------------

    @property
    def paused(self) -> bool:
        return not self._unpaused.is_set()

    async def pause(self) -> None:
        """Stop speaking now. The interrupted line is replayed from its start on ``resume()``."""
        if self.paused:
            return
        self._unpaused.clear()
        self.pauses += 1
        for cb in list(self._on_pause):
            await cb()

    async def resume(self) -> None:
        if not self.paused:
            return
        for cb in list(self._on_resume):
            await cb()
        self._unpaused.set()

    async def wait_unpaused(self) -> None:
        await self._unpaused.wait()

    # ---- answers (task 5.3) ----------------------------------------------------------------

    def interject(self, script: Any, question_id: str) -> None:
        """Queue a cleared answer; ``speak()`` voices it before the next briefing line. Only a
        ``ClearedScript`` is accepted, so an answer cannot skip the Standards Desk."""
        from app.standards_desk import ClearedScript

        if not isinstance(script, ClearedScript):
            raise TypeError("the Anchor speaks only a ClearedScript (standards_desk.clear_for_air)")
        self._interjections.append((script, question_id))

    def take_interjection(self) -> tuple[Any, str] | None:
        return self._interjections.popleft() if self._interjections else None

    def on_pause(self, cb: Callable[[], Awaitable[None]]) -> None:
        self._on_pause.append(cb)

    def on_resume(self, cb: Callable[[], Awaitable[None]]) -> None:
        self._on_resume.append(cb)


class MemorySession(VoiceSession):
    """Collects everything (tests)."""

    def __init__(self, realtime: bool = False) -> None:
        super().__init__()
        self.realtime = realtime
        self.audio = bytearray()
        self.events: list[dict[str, Any]] = []
        self.chunks = 0

    async def send_audio(self, pcm: bytes) -> None:
        self.audio.extend(pcm)
        self.chunks += 1

    async def send_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class WavFileSession(VoiceSession):
    """Writes a mono 16-bit WAV file and keeps the events (CLI)."""

    def __init__(self, path: Path, sample_rate: int) -> None:
        super().__init__()
        self.path = path
        self.events: list[dict[str, Any]] = []
        self._wav = wave.open(str(path), "wb")  # noqa: SIM115 - closed in close()
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)

    async def send_audio(self, pcm: bytes) -> None:
        self._wav.writeframes(pcm)

    async def send_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def close(self) -> None:
        self._wav.close()


class WebSocketSession(VoiceSession):
    """Binary messages are PCM16 chunks; text messages are the JSON events. Sends are serialised
    because the Anchor and the Caller share the socket."""

    realtime = True

    def __init__(self, ws: WebSocket) -> None:
        super().__init__()
        self.ws = ws
        self.current_line_id: UUID | None = None  # last line announced, for the Caller
        self._send_lock = asyncio.Lock()

    async def send_audio(self, pcm: bytes) -> None:
        async with self._send_lock:
            await self.ws.send_bytes(pcm)

    async def send_event(self, event: dict[str, Any]) -> None:
        if event.get("type") == "line":
            self.current_line_id = UUID(event["line_id"])
        async with self._send_lock:
            await self.ws.send_json(event)
