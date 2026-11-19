"""Anchor: speaks cleared scripts through a Pipecat pipeline.

Node: context/nodes/anchor.md

    report = await speak(cleared, session)   # only a ClearedScript is accepted
"""

from app.anchor.pipeline import AnchorError, LineTiming, SpeakReport, speak
from app.anchor.session import MemorySession, VoiceSession, WavFileSession, WebSocketSession
from app.anchor.tts import AnchorConfigError, FakeTTSService, make_tts

__all__ = [
    "AnchorConfigError",
    "AnchorError",
    "FakeTTSService",
    "LineTiming",
    "MemorySession",
    "SpeakReport",
    "VoiceSession",
    "WavFileSession",
    "WebSocketSession",
    "make_tts",
    "speak",
]
