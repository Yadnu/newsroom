"""STT adapters behind one factory (decision 0004). ``caller_stt`` picks the provider.

- ``deepgram``: Pipecat's Deepgram live service (linear16 at ``caller_sample_rate``).
- ``fake``: scripted transcripts for tests, CI, and running without a key.
"""

from collections.abc import AsyncGenerator, Sequence
from typing import Any

from pipecat.frames.frames import Frame, InterimTranscriptionFrame, TranscriptionFrame
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import STTService
from pipecat.utils.time import time_now_iso8601

import app.anchor.tts  # noqa: F401  (quiets Pipecat's loguru output)
from app.caller.types import CallerConfigError
from app.config import Settings


class FakeSTTService(STTService):
    """Emits scripted words as audio arrives: after every ``bytes_per_word`` bytes of audio one
    more word of the current phrase is heard (interim); the phrase becomes final once complete.
    ``phrases`` are consumed in order, one per utterance."""

    def __init__(
        self, phrases: Sequence[str] = (), *, bytes_per_word: int = 3200, **kwargs: Any
    ) -> None:
        kwargs.setdefault("settings", STTSettings(model=None, language=None))
        super().__init__(**kwargs)
        self.phrases = list(phrases)
        self.bytes_per_word = bytes_per_word
        self.audio_bytes = 0
        self._heard = 0  # words of the current phrase emitted

    def can_generate_metrics(self) -> bool:
        return False

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        self.audio_bytes += len(audio)
        if not self.phrases:
            yield None
            return
        words = self.phrases[0].split()
        target = min(len(words), self.audio_bytes // self.bytes_per_word)
        if target <= self._heard:
            yield None
            return
        self._heard = target
        text = " ".join(words[:target])
        if target < len(words):
            yield InterimTranscriptionFrame(text, "", time_now_iso8601())
            return
        yield TranscriptionFrame(text, "", time_now_iso8601(), finalized=True)
        self.phrases.pop(0)
        self._heard = 0
        self.audio_bytes = 0


def make_stt(settings: Settings) -> STTService:
    if settings.caller_stt == "fake":
        return FakeSTTService(sample_rate=settings.caller_sample_rate)
    key = settings.deepgram_api_key
    if key is None or not key.get_secret_value():
        raise CallerConfigError("NEWSROOM_DEEPGRAM_API_KEY is not set")
    from pipecat.services.deepgram.stt import DeepgramSTTService

    return DeepgramSTTService(
        api_key=key.get_secret_value(),
        sample_rate=settings.caller_sample_rate,
        settings=DeepgramSTTService.Settings(
            model=settings.deepgram_model,
            smart_format=True,
            interim_results=True,
            punctuate=True,
        ),
    )
