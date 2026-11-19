"""Standards Desk: guardrails on both ends of the pipeline.

Node: context/nodes/standards-desk.md

    cleared = await clear_for_air(reviewed)   # the Anchor only accepts a ClearedScript
"""

from app.standards_desk.clear import clear_for_air
from app.standards_desk.screen import ScreenResult, screen_caller
from app.standards_desk.stored import BriefingNotFoundError, clear_stored, load_script
from app.standards_desk.types import (
    Block,
    BlockRule,
    ClearedLine,
    ClearedScript,
    NotClearedError,
)

__all__ = [
    "Block",
    "BlockRule",
    "BriefingNotFoundError",
    "ClearedLine",
    "ClearedScript",
    "NotClearedError",
    "ScreenResult",
    "clear_for_air",
    "clear_stored",
    "load_script",
    "screen_caller",
]
