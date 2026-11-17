"""Public types for the LLM gateway."""

from dataclasses import dataclass
from typing import Literal, TypedDict

# Task names are routing keys (decision 0002). Each must have an entry in Settings.llm_routes.
TaskName = Literal["draft", "judge", "classify", "answer"]
TASK_NAMES: tuple[TaskName, ...] = ("draft", "judge", "classify", "answer")

EmbedInputType = Literal["document", "query"]


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class Usage:
    """What one gateway call cost. Totals across retries and structured-output resamples."""

    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: float
    attempts: int


class LLMError(Exception):
    """Base class for gateway errors."""


class LLMConfigError(LLMError):
    """Missing key, unknown task, or unpriced model."""


class LLMProviderError(LLMError):
    """The provider failed after all retries, or returned a non-retryable error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class StructuredOutputError(LLMError):
    """The model did not produce output matching the schema, even after resampling."""
