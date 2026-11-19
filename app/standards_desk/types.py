"""The air gate. A ``ClearedScript`` can only be built by ``clear_for_air()``, so any code that
holds one (the Anchor) knows every line passed the Standards Desk."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

_CLEARANCE = object()  # private token: only clear.py passes it


class BlockRule(StrEnum):
    unapproved = "unapproved"
    unchecked_fact = "unchecked_fact"
    long_quote = "long_quote"
    verbatim = "verbatim"
    opinion = "opinion"
    story_dropped = "story_dropped"


class NotClearedError(Exception):
    """No line of the script survived the Standards Desk."""

    def __init__(self, message: str, blocked: tuple["Block", ...] = ()) -> None:
        super().__init__(message)
        self.blocked = blocked


@dataclass(frozen=True, slots=True)
class ClearedLine:
    id: UUID
    story_id: UUID
    order: int
    text: str
    claim_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class Block:
    line_id: UUID
    order: int
    rule: BlockRule
    reason: str


class ClearedScript:
    """Immutable. ``ClearedScript(...)`` raises; ``clear_for_air()`` issues one through ``_issue``
    with a private token. There is no ``replace``-style copy that could swap in other lines."""

    __slots__ = ("blocked", "briefing_id", "lines")
    briefing_id: UUID
    lines: tuple[ClearedLine, ...]  # in air order
    blocked: tuple[Block, ...]

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("ClearedScript is built only by standards_desk.clear_for_air()")

    @classmethod
    def _issue(
        cls,
        token: object,
        briefing_id: UUID,
        lines: tuple[ClearedLine, ...],
        blocked: tuple[Block, ...],
    ) -> "ClearedScript":
        if token is not _CLEARANCE:
            raise TypeError("ClearedScript is built only by standards_desk.clear_for_air()")
        self = object.__new__(cls)
        object.__setattr__(self, "briefing_id", briefing_id)
        object.__setattr__(self, "lines", tuple(lines))
        object.__setattr__(self, "blocked", tuple(blocked))
        return self

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ClearedScript is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ClearedScript is immutable")

    def __repr__(self) -> str:
        return (
            f"ClearedScript(briefing_id={self.briefing_id}, lines={len(self.lines)},"
            f" blocked={len(self.blocked)})"
        )
