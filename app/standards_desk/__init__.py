"""Standards Desk: guardrails on both ends of the pipeline.

Node: context/nodes/standards-desk.md

    cleared = await clear_for_air(reviewed)   # the Anchor only accepts a ClearedScript
"""

from app.standards_desk.clear import clear_for_air
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
    "ClearedLine",
    "ClearedScript",
    "NotClearedError",
    "clear_for_air",
]
