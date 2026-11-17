"""structlog setup. JSON lines by default, console output when ``log_json`` is off.

Bind ``component`` and ``briefing_id`` per call site: ``get_logger(__name__).bind(...)``.
"""

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any, TextIO

import structlog

from app.config import Settings

_SECRET_KEY = re.compile(r"(api_?key|secret|token|password|authorization)", re.I)
REDACTED = "[redacted]"


def redact_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Replace the value of any field whose name looks like a secret."""
    for key in event_dict:
        if _SECRET_KEY.search(key):
            event_dict[key] = REDACTED
    return event_dict


def configure_logging(settings: Settings, stream: TextIO | None = None) -> None:
    """``stream`` defaults to stdout; the CLI passes stderr so stdout stays clean for output."""
    level = logging.getLevelNamesMapping()[settings.log_level]
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_secrets,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(name)
    return logger
