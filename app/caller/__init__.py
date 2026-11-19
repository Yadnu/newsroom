"""Caller: listener speech to classified questions.

Node: context/nodes/caller.md

    async for event in listen(pcm_chunks, context):   # Interim | CallerQuestion
        ...
"""

from app.caller.context import context_for
from app.caller.intent import classify
from app.caller.pipeline import listen
from app.caller.stt import FakeSTTService, make_stt
from app.caller.types import (
    CallerConfigError,
    CallerContext,
    CallerEvent,
    CallerQuestion,
    Intent,
    Interim,
    StoryRef,
)

__all__ = [
    "CallerConfigError",
    "CallerContext",
    "CallerEvent",
    "CallerQuestion",
    "FakeSTTService",
    "Intent",
    "Interim",
    "StoryRef",
    "classify",
    "context_for",
    "listen",
    "make_stt",
]
