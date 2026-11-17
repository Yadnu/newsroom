"""Smoke test: every Python node in the context graph has an importable package."""

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODES = ROOT / "context" / "nodes"


def _python_node_paths() -> list[tuple[str, str]]:
    out = []
    for p in sorted(NODES.glob("*.md")):
        m = re.search(r"^code:\s*(\S+)", p.read_text(encoding="utf-8"), re.M)
        if m and m.group(1).startswith("app/"):
            out.append((p.stem, m.group(1).rstrip("/")))
    return out


@pytest.mark.parametrize(("node_id", "code_path"), _python_node_paths())
def test_node_package_imports_and_points_to_node(node_id: str, code_path: str) -> None:
    module = importlib.import_module(code_path.replace("/", "."))
    assert module.__doc__ is not None
    assert f"context/nodes/{node_id}.md" in module.__doc__
