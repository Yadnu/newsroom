"""Intent classification through the llm-gateway's ``classify`` route (task 5.1).

The transcript is untrusted listener speech: it only ever goes, escaped, into the user turn.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.archive import span
from app.caller.types import CallerContext, Intent
from app.log import get_logger
from app.shared import llm
from app.shared.llm import LLMError, Message
from app.writer.prompts import escape_text, load_prompt, render

MIN_WORDS = 2  # shorter than this is noise, a cough, or "um"

log = get_logger(__name__)


class IntentOut(BaseModel):
    intent: Literal["follow_up", "background", "off_topic"]
    story: str  # "S<n>" or "none"
    question: str


def build_messages(transcript: str, context: CallerContext) -> list[Message]:
    refs = {s.id: f"S{i}" for i, s in enumerate(context.stories, 1)}
    stories = (
        "\n".join(
            f"{refs[s.id]}: {escape_text(s.title)}"
            + (f"\n    Heard: {escape_text(s.heard)}" if s.heard else "")
            for s in context.stories
        )
        or "(none)"
    )
    current = refs.get(context.current_story_id, "none") if context.current_story_id else "none"
    return [
        {"role": "system", "content": load_prompt("caller/classify_system")},
        {
            "role": "user",
            "content": render(
                "caller/classify_user",
                stories=stories,
                current=current,
                question=escape_text(transcript.strip()),
            ),
        },
    ]


def story_for(ref: str, context: CallerContext) -> UUID | None:
    ref = ref.strip().upper()
    if ref.startswith("S") and ref[1:].isdigit():
        i = int(ref[1:])
        if 1 <= i <= len(context.stories):
            return context.stories[i - 1].id
    return None


async def classify(transcript: str, context: CallerContext) -> Intent:
    words = transcript.split()
    with span("caller", "classify", context.briefing_id, words=len(words)) as s:
        if len(words) < MIN_WORDS:
            s.set(intent="off_topic", skipped=True)
            return Intent("off_topic", None, "")
        try:
            out = await llm.complete("classify", build_messages(transcript, context), IntentOut)
        except LLMError as e:
            log.warning("caller.classify_failed", error=type(e).__name__)
            s.set(intent="unknown", error=type(e).__name__)
            return Intent("unknown", None, "")
        story_id = story_for(out.story, context) if out.intent != "off_topic" else None
        restated = out.question.strip() if out.intent != "off_topic" else ""
        s.set(intent=out.intent, story=out.story, story_id=story_id)
        return Intent(out.intent, story_id, restated)
