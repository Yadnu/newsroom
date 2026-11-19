"""Caller data types (task 5.1)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

IntentName = Literal["follow_up", "background", "off_topic", "unknown"]


class CallerConfigError(RuntimeError):
    """The configured STT adapter is missing a key or setting."""


@dataclass(frozen=True, slots=True)
class StoryRef:
    id: UUID
    title: str
    heard: str = ""  # what the Anchor read about it (cleared lines), so follow-ups can match


@dataclass(frozen=True, slots=True)
class CallerContext:
    """What the listener could be asking about: the briefing's stories, in air order."""

    briefing_id: UUID
    stories: tuple[StoryRef, ...]
    current_story_id: UUID | None = None  # the story being read when they spoke


@dataclass(frozen=True, slots=True)
class Intent:
    intent: IntentName
    story_id: UUID | None
    restated: str  # the question in clean words ("" when off topic or unknown)


@dataclass(frozen=True, slots=True)
class Interim:
    """Words heard so far in the current utterance."""

    text: str


@dataclass(frozen=True, slots=True)
class CallerQuestion:
    transcript: str
    intent: IntentName
    story_id: UUID | None
    restated: str
    id: UUID = field(default_factory=uuid4)
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


CallerEvent = Interim | CallerQuestion
