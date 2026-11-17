"""LLM gateway: the single client for every LLM and embedding call.

Node: context/nodes/llm-gateway.md

    result = await complete("judge", messages, Verdict)
    vectors = await embed(["passage one", "passage two"])

Use the ``*_with_usage`` variants when the caller needs tokens, cost and latency.
"""

from collections.abc import Sequence

from pydantic import BaseModel

from app.config import get_settings
from app.shared.llm.gateway import Gateway
from app.shared.llm.types import (
    EmbedInputType,
    LLMConfigError,
    LLMError,
    LLMProviderError,
    Message,
    StructuredOutputError,
    TaskName,
    Usage,
)

__all__ = [
    "EmbedInputType",
    "Gateway",
    "LLMConfigError",
    "LLMError",
    "LLMProviderError",
    "Message",
    "StructuredOutputError",
    "TaskName",
    "Usage",
    "aclose",
    "complete",
    "complete_with_usage",
    "embed",
    "embed_with_usage",
    "get_gateway",
    "set_gateway",
]

_gateway: Gateway | None = None


def get_gateway() -> Gateway:
    global _gateway
    if _gateway is None:
        _gateway = Gateway(get_settings())
    return _gateway


def set_gateway(gateway: Gateway | None) -> None:
    """Swap the process-wide gateway (tests, or a custom transport)."""
    global _gateway
    _gateway = gateway


async def aclose() -> None:
    global _gateway
    if _gateway is not None:
        await _gateway.aclose()
        _gateway = None


async def complete_with_usage[T: BaseModel](
    task: TaskName, messages: Sequence[Message], schema: type[T]
) -> tuple[T, Usage]:
    return await get_gateway().complete(task, messages, schema)


async def complete[T: BaseModel](task: TaskName, messages: Sequence[Message], schema: type[T]) -> T:
    result, _ = await get_gateway().complete(task, messages, schema)
    return result


async def embed_with_usage(
    texts: Sequence[str], input_type: EmbedInputType | None = "document"
) -> tuple[list[list[float]], Usage]:
    return await get_gateway().embed(texts, input_type)


async def embed(
    texts: Sequence[str], input_type: EmbedInputType | None = "document"
) -> list[list[float]]:
    vectors, _ = await get_gateway().embed(texts, input_type)
    return vectors
