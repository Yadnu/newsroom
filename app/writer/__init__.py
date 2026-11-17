"""Writer: drafts the spoken script and tags every factual sentence with claims.

Node: context/nodes/writer.md
"""

from app.writer.draft import DraftClaim, DraftLine, Script, WriterError, draft_script

__all__ = ["DraftClaim", "DraftLine", "Script", "WriterError", "draft_script"]
