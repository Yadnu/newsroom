"""Typed questions (task 9.6): the same classify -> screen path as a spoken utterance, without STT.

    question = await question_from_text("What did Nvidia say?", context)

The text is untrusted exactly like a transcript: ``classify`` escapes it into the user turn, and
``screen_caller`` judges it before anything answers it.
"""

from collections.abc import Awaitable, Callable

from app.archive import span
from app.caller.intent import classify
from app.caller.types import CallerContext, CallerQuestion, Intent
from app.standards_desk.screen import ScreenResult, screen_caller

MAX_TYPED_CHARS = 500  # longer text is cut before classify; the screen's word limit still applies

Classifier = Callable[[str, CallerContext], Awaitable[Intent]]
Screener = Callable[[str, str | None], Awaitable[ScreenResult]]


def clean_typed(text: str) -> str:
    """Collapse whitespace and cap the length of what a reader typed."""
    return " ".join(text.split())[:MAX_TYPED_CHARS].strip()


async def question_from_text(
    text: str,
    context: CallerContext,
    *,
    classifier: Classifier | None = None,
    screener: Screener | None = None,
) -> CallerQuestion:
    transcript = clean_typed(text)
    with span("caller", "question", context.briefing_id, transcript=transcript, typed=True) as s:
        intent = await (classifier or classify)(transcript, context)
        screen = await (screener or screen_caller)(transcript, intent.intent)
        s.set(
            intent=intent.intent,
            story_id=intent.story_id,
            allowed=screen.allowed,
            screen=screen.category,
        )
    return CallerQuestion(
        transcript, intent.intent, intent.story_id, intent.restated, screen=screen
    )
