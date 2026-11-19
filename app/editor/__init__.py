"""Editor: LLM judge that checks each claim against its sources.

Node: context/nodes/editor.md
"""

from app.editor.judge import (
    ClaimVerdict,
    EvidencePassage,
    JudgedScript,
    judge_claim,
    judge_script,
)
from app.editor.retrieve import Passage, chunk_text, retrieve_evidence
from app.editor.review import ReviewedScript, review_script

__all__ = [
    "ClaimVerdict",
    "EvidencePassage",
    "JudgedScript",
    "Passage",
    "ReviewedScript",
    "chunk_text",
    "judge_claim",
    "judge_script",
    "retrieve_evidence",
    "review_script",
]
