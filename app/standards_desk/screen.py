"""``screen_caller()``: check a listener's question before anything answers it (task 5.2,
decision 0019).

Layer 1, rules (no call): too short, too long, injection phrasing, insults aimed at the anchor,
and the Caller's own ``off_topic`` intent. Layer 2, LLM moderation on the gateway's ``classify``
route (labels only). If that call fails the question is judged on the rules alone (fail open).
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.archive import span
from app.config import get_settings
from app.log import get_logger
from app.shared import llm
from app.shared.llm import LLMError, Message
from app.writer.prompts import escape_text, load_prompt, render

ScreenCategory = Literal["ok", "empty", "too_long", "abusive", "injection", "off_topic"]
CheckedBy = Literal["rules", "llm", "intent"]

MIN_WORDS = 2

# Instruction hijacking. Each pattern needs the whole move, so news questions that merely contain
# "system", "act", "rules" or "instructions" pass ("Did the regulator ignore the rules on exports?",
# "Who leaked the system prompt of that chatbot?"). Tuned against evals/data/redteam_v1.json.
_SEP = r"[\s.,:;!-]+"
_QUAL = r"(your|previous|prior|above|earlier|preceding|these|those|my|all|any|every)"
_OBJ = (
    r"(instructions?|rules?|guidelines?|prompts?|polic(y|ies)|programming|safeguards?|filters?|"
    r"guardrails?)"
)
INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        rf"\b(ignore|disregard|forget|override|bypass){_SEP}(the{_SEP})?({_QUAL}{_SEP}){{1,3}}"
        rf"(\w+{_SEP})?{_OBJ}\b",
        r"\b(forget|ignore|disregard)\s+(everything|all)\s+(you\s*('ve| have| were)( been)? told|"
        r"above|before|so far)",
        r"\byour\s+(system|hidden|initial|original|secret)\s+(prompt|instructions?)\b",
        r"\b(show|print|reveal|repeat|read|give)( me)?\s+the\s+(system|hidden|initial|original|"
        r"secret)\s+prompt\b",
        r"\b(reveal|show|print|repeat|read( me)?|tell me|what are|translate|summari[sz]e|spell out|"
        r"list)\b.{0,20}\byour\b.{0,15}\b(instructions?|rules|prompt|guidelines|configuration)\b",
        r"\byou are now\b|\bfrom now on,? you\b",
        r"\b(pretend|act|behave)\b.{0,10}\b(to be|as if you|like you are|as an? (ai|assistant|"
        r"bot|model|chatbot|different))\b",
        r"\b(enable|enter|activate|switch (to|on|into)|turn on|go into|unlock)\b.{0,12}"
        r"\b(developer|god|debug|admin|dan|jailbreak|unrestricted|unfiltered)\s+mode\b|"
        r"\bjail ?break (yourself|the (anchor|assistant|bot|system))\b|^\W*jail ?break\b",
        r"\b(say|repeat)\s+(after me|the (following|words?|phrase))\b|"
        r"\bsay exactly (this|these|what i)\b",
        r"</?\s*(system|assistant|user|instructions?)\s*>|\[/?inst\]|^\s*#{2,}",
    )
]
# Insults aimed at the anchor itself. Deliberately short: the LLM layer catches the rest.
ABUSE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bshut (the f\w* )?up\b",
        r"\bf+u+c*k+ (you|off|this)\b|\bscrew you\b",
        r"\byou(\s*'?re| are)? (so |such |really |very )?(an? )?"
        r"(stupid|idiot|moron|dumb|useless|worthless|pathetic)\b",
        r"\b(stupid|dumb|useless|worthless) (bot|robot|machine|ai|anchor)\b",
        r"\bkill yourself\b|\bkys\b",
    )
]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ScreenResult:
    allowed: bool
    category: ScreenCategory
    reason: str
    checked_by: CheckedBy


class ModerationOut(BaseModel):
    abusive: bool
    injection: bool
    reason: str


def screen_rules(transcript: str, intent: str | None, max_words: int) -> ScreenResult | None:
    """The deterministic layer. ``None`` means no rule blocked."""
    words = transcript.split()
    if len(words) < MIN_WORDS:
        return ScreenResult(False, "empty", "too short to be a question", "rules")
    if len(words) > max_words:
        return ScreenResult(False, "too_long", f"{len(words)} words (limit {max_words})", "rules")
    for p in INJECTION_PATTERNS:
        if m := p.search(transcript):
            return ScreenResult(
                False, "injection", f"tries to instruct the system: {m.group(0)!r}", "rules"
            )
    for p in ABUSE_PATTERNS:
        if m := p.search(transcript):
            return ScreenResult(False, "abusive", f"abusive: {m.group(0)!r}", "rules")
    if intent == "off_topic":
        return ScreenResult(False, "off_topic", "not about the news in this briefing", "intent")
    return None


def build_messages(transcript: str) -> list[Message]:
    return [
        {"role": "system", "content": load_prompt("standards/screen_system")},
        {
            "role": "user",
            "content": render("standards/screen_user", question=escape_text(transcript.strip())),
        },
    ]


async def screen_caller(transcript: str, intent: str | None = None) -> ScreenResult:
    """Allow or block a listener's question, with a reason. Every block is logged."""
    settings = get_settings()
    with span("standards-desk", "screen_caller", words=len(transcript.split())) as s:
        result = screen_rules(transcript, intent, settings.standards_max_question_words)
        if result is None:
            try:
                out = await llm.complete("classify", build_messages(transcript), ModerationOut)
            except LLMError as e:
                log.warning("standards.screen_llm_failed", error=type(e).__name__)
                s.set(llm_error=type(e).__name__)
                result = ScreenResult(True, "ok", "rules only (moderation unavailable)", "rules")
            else:
                if out.injection:
                    result = ScreenResult(False, "injection", out.reason or "injection", "llm")
                elif out.abusive:
                    result = ScreenResult(False, "abusive", out.reason or "abusive", "llm")
                else:
                    result = ScreenResult(True, "ok", "", "llm")
        s.set(allowed=result.allowed, category=result.category, checked_by=result.checked_by)
        if not result.allowed:
            with span(
                "standards-desk",
                "block_caller",
                category=result.category,
                reason=result.reason,
                checked_by=result.checked_by,
            ):
                pass
    return result
