"""``summarize_story()``: a short card summary of a story for the Press feed (task 8.2).

One LLM call (task "draft"). Sources go in escaped ``<source>`` blocks in the user turn; the system
prompt is a fixed template (only the target length is filled in). The summary paraphrases: it is
rejected when it quotes 15 words or more, or is too short or too long. The caller (``app.press``)
also checks it against the Standards Desk's copied-words rule before storing it. Summaries are not
fact-checked; the telecast is.
"""

from collections.abc import Sequence

from pydantic import BaseModel

from app.archive import span
from app.config import get_settings
from app.shared import llm
from app.writer.draft import SourceText, WriterError, quote_violations, sources_block
from app.writer.prompts import escape_text, render

TARGET_WORDS = 60
MIN_WORDS = 20
MAX_WORDS = 90


class StorySummaryOut(BaseModel):
    summary: str


def summary_problems(text: str) -> list[str]:
    n = len(text.split())
    problems = quote_violations(text)
    if n < MIN_WORDS:
        problems.append(f"the summary has {n} words; write at least {MIN_WORDS}")
    if n > MAX_WORDS:
        problems.append(f"the summary has {n} words; keep it under {MAX_WORDS}")
    return problems


def summary_messages(
    title: str, sources: Sequence[SourceText], max_chars: int, feedback: Sequence[str] = ()
) -> list[llm.Message]:
    block, _refs = sources_block(sources, max_chars)
    messages: list[llm.Message] = [
        {"role": "system", "content": render("writer/summary_system", target_words=TARGET_WORDS)},
        {
            "role": "user",
            "content": render("writer/summary_user", story_title=escape_text(title), sources=block),
        },
    ]
    if feedback:
        messages.append(
            {
                "role": "user",
                "content": "Your last summary broke these rules:\n- "
                + "\n- ".join(feedback)
                + "\nWrite a new summary in your own words.",
            }
        )
    return messages


async def summarize_story(
    story_id: object, title: str, sources: Sequence[SourceText], feedback: Sequence[str] = ()
) -> str:
    """A ~60-word paraphrase of ``sources``. Raises ``WriterError`` if the model breaks the rules
    twice, and ``llm.LLMError`` if the call fails."""
    if not sources:
        raise WriterError(f"story {story_id}: no sources to summarize")
    max_chars = get_settings().writer_source_max_chars
    messages = summary_messages(title, sources, max_chars, feedback)
    with span("writer", "summarize_story", story_id=story_id, sources=len(sources)) as s:
        out = await llm.complete("draft", messages, StorySummaryOut)
        text = " ".join(out.summary.split())
        problems = summary_problems(text)
        attempts = 1
        if problems:
            messages = [
                *summary_messages(title, sources, max_chars, [*feedback, *problems]),
            ]
            out = await llm.complete("draft", messages, StorySummaryOut)
            text = " ".join(out.summary.split())
            problems = summary_problems(text)
            attempts = 2
        s.set(attempts=attempts, words=len(text.split()), problems=problems)
        if problems:
            raise WriterError(f"story {story_id}: " + "; ".join(problems))
    return text
