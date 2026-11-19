"""Prompt files live in ``prompts/`` at the repo root, one folder per component.

Templates use ``string.Template`` (``$name``), so braces in fetched text never break formatting.
Fetched text is only ever substituted into user-turn templates, never system prompts.
"""

from functools import cache
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@cache
def load_prompt(name: str) -> str:
    """``name`` like ``"writer/draft_system"`` (no extension)."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def render(name: str, **values: object) -> str:
    return Template(load_prompt(name)).substitute({k: str(v) for k, v in values.items()})


def escape_text(text: str) -> str:
    """Escape fetched text for a ``<source>`` body so it cannot close or forge a block."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_attr(text: str) -> str:
    """Escape a value placed inside a double-quoted attribute."""
    return escape_text(text).replace('"', "&quot;")
