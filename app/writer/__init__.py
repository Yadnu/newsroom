"""Writer: drafts the spoken script and tags every factual sentence with claims.

Node: context/nodes/writer.md
"""

from app.writer.draft import DraftClaim, DraftLine, Script, WriterError, draft_script
from app.writer.rewrite import ClaimFeedback, rewrite_line

__all__ = [
    "ClaimFeedback",
    "DraftClaim",
    "DraftLine",
    "Script",
    "WriterError",
    "draft_script",
    "rewrite_line",
]
