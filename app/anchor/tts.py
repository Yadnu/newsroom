"""TTS adapters behind one factory (decision 0004). ``anchor_tts`` picks the provider.

- ``cartesia``: Pipecat's Cartesia websocket service (streaming PCM).
- ``fake``: silent PCM, ``FAKE_MS_PER_WORD`` per word, in the same frame types. For tests, CI, and
  running the pipeline without a key.
"""

import asyncio
import sys
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from loguru import logger as pipecat_logger
from pipecat.frames.frames import Frame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService

from app.config import Settings

FAKE_MS_PER_WORD = 60
_FAKE_CHUNK_MS = 100


def quiet_pipecat(level: str = "WARNING") -> None:
    """Pipecat logs through loguru at DEBUG by default; keep only warnings and errors."""
    pipecat_logger.remove()
    pipecat_logger.add(sys.stderr, level=level)


quiet_pipecat()


class AnchorConfigError(RuntimeError):
    """The configured TTS adapter is missing a key or setting."""


class FakeTTSService(TTSService):
    """Deterministic silent speech: ``FAKE_MS_PER_WORD`` ms of PCM16 per word."""

    def __init__(self, *, ms_per_word: int = FAKE_MS_PER_WORD, **kwargs: Any) -> None:
        kwargs.setdefault("settings", TTSSettings(model=None, voice=None, language=None))
        super().__init__(push_start_frame=True, push_stop_frames=True, **kwargs)
        self.ms_per_word = ms_per_word
        self.spoken: list[str] = []

    def can_generate_metrics(self) -> bool:
        return False

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        self.spoken.append(text)
        total = fake_audio_bytes(text, self.sample_rate, self.ms_per_word)
        chunk = self.sample_rate * _FAKE_CHUNK_MS // 1000 * 2

        async def pcm() -> AsyncIterator[bytes]:
            for i in range(0, total, chunk):
                await asyncio.sleep(0)
                yield b"\x00" * min(chunk, total - i)

        async for frame in self._stream_audio_frames_from_iterator(
            pcm(), in_sample_rate=self.sample_rate, context_id=context_id
        ):
            yield frame


def fake_audio_bytes(text: str, sample_rate: int, ms_per_word: int = FAKE_MS_PER_WORD) -> int:
    """PCM16 mono bytes the fake service produces for ``text``."""
    return len(text.split()) * sample_rate * ms_per_word // 1000 * 2


def make_tts(settings: Settings) -> TTSService:
    if settings.anchor_tts == "fake":
        return FakeTTSService(sample_rate=settings.anchor_sample_rate)
    key = settings.cartesia_api_key
    if key is None or not key.get_secret_value():
        raise AnchorConfigError("NEWSROOM_CARTESIA_API_KEY is not set")
    if not settings.cartesia_voice_id:
        raise AnchorConfigError("NEWSROOM_CARTESIA_VOICE_ID is not set")
    from pipecat.services.cartesia.tts import CartesiaTTSService

    tts_settings = CartesiaTTSService.Settings(voice=settings.cartesia_voice_id)
    if settings.cartesia_model:
        tts_settings.model = settings.cartesia_model
    return CartesiaTTSService(
        api_key=key.get_secret_value(),
        sample_rate=settings.anchor_sample_rate,
        settings=tts_settings,
    )
