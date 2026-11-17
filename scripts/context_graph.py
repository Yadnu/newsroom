#!/usr/bin/env python3
"""Context graph tool for the Newsroom repo. Standard library only.

Usage:
  python scripts/context_graph.py build            regenerate the index block in context/GRAPH.md
  python scripts/context_graph.py check            validate nodes, edges, decisions, and the index
  python scripts/context_graph.py read <node-id>   print the files an agent should read for a task on that node
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CTX = ROOT / "context"
NODES = CTX / "nodes"
DECISIONS = CTX / "decisions"
GRAPH = CTX / "GRAPH.md"
STATE = CTX / "STATE.md"

START, END = "<!-- graph:start -->", "<!-- graph:end -->"
REQUIRED = ("id", "type", "status", "phase", "code", "depends_on", "feeds", "decisions")
STATUSES = {"planned", "in-progress", "done", "blocked"}
TYPES = {"component", "shared", "app"}
MAX_LINES = 120


def parse_frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    data: dict[str, object] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        val = raw.strip()
        if val.startswith("[") and val.endswith("]"):
            data[key.strip()] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
        else:
            data[key.strip()] = val.strip("\"'")
    return data


def load_nodes() -> dict[str, dict[str, object]]:
    nodes = {}
    for p in sorted(NODES.glob("*.md")):
        fm = parse_frontmatter(p)
        fm["_path"] = p
        nodes[str(fm.get("id", p.stem))] = fm
    return nodes


def load_decisions() -> dict[str, dict[str, object]]:
    out = {}
    for p in sorted(DECISIONS.glob("*.md")):
        fm = parse_frontmatter(p)
        did = str(fm.get("id", ""))
        if did and did != "NNNN":
            fm["_path"] = p
            out[did] = fm
    return out


def as_list(v: object) -> list[str]:
    return list(v) if isinstance(v, list) else []


def edges(nodes: dict[str, dict[str, object]]) -> list[tuple[str, str]]:
    """Directed data-flow edges a -> b, merged from `feeds` and `depends_on`."""
    es: set[tuple[str, str]] = set()
    for nid, n in nodes.items():
        for t in as_list(n.get("feeds")):
            es.add((nid, t))
        for s in as_list(n.get("depends_on")):
            es.add((s, nid))
    return sorted(es)


def render(nodes: dict[str, dict[str, object]]) -> str:
    rows = ["| Node | Type | Status | Phase | Code | Depends on | Feeds | Decisions |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for nid, n in sorted(nodes.items(), key=lambda kv: (int(str(kv[1].get("phase", 99)) or 99), kv[0])):
        rows.append(
            f"| [{nid}](nodes/{nid}.md) | {n.get('type','')} | {n.get('status','')} | {n.get('phase','')} "
            f"| `{n.get('code','')}` | {', '.join(as_list(n.get('depends_on'))) or '-'} "
            f"| {', '.join(as_list(n.get('feeds'))) or '-'} | {', '.join(as_list(n.get('decisions'))) or '-'} |"
        )
    safe = lambda s: s.replace("-", "_")
    mer = ["```mermaid", "flowchart LR"]
    for nid, n in sorted(nodes.items()):
        mer.append(f"  {safe(nid)}[\"{nid} ({n.get('status','')})\"]")
    for a, b in edges(nodes):
        if a in nodes and b in nodes:
            mer.append(f"  {safe(a)} --> {safe(b)}")
    mer.append("```")
    return "\n".join([START, "", "## Nodes", "", *rows, "", "## Edges", "", *mer, "", END])


def build() -> int:
    nodes = load_nodes()
    text = GRAPH.read_text(encoding="utf-8")
    if START not in text or END not in text:
        print(f"error: {GRAPH} is missing the {START} / {END} markers")
        return 1
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: render(nodes), text, flags=re.S)
    GRAPH.write_text(new, encoding="utf-8")
    print(f"built GRAPH.md: {len(nodes)} nodes, {len(edges(nodes))} edges")
    return 0


def check() -> int:
    errors: list[str] = []
    warns: list[str] = []
    nodes = load_nodes()
    decisions = load_decisions()

    for nid, n in nodes.items():
        p: Path = n["_path"]  # type: ignore[assignment]
        rel = p.relative_to(ROOT)
        for k in REQUIRED:
            if k not in n:
                errors.append(f"{rel}: missing frontmatter key '{k}'")
        if nid != p.stem:
            errors.append(f"{rel}: id '{nid}' does not match file name")
        if n.get("status") not in STATUSES:
            errors.append(f"{rel}: status must be one of {sorted(STATUSES)}")
        if n.get("type") not in TYPES:
            errors.append(f"{rel}: type must be one of {sorted(TYPES)}")
        for key in ("depends_on", "feeds"):
            for t in as_list(n.get(key)):
                if t not in nodes:
                    errors.append(f"{rel}: {key} references unknown node '{t}'")
        for d in as_list(n.get("decisions")):
            if d not in decisions:
                errors.append(f"{rel}: decision '{d}' not found in context/decisions/")
        if n.get("status") in {"in-progress", "done"} and not (ROOT / str(n.get("code", ""))).exists():
            errors.append(f"{rel}: status is {n.get('status')} but code path '{n.get('code')}' does not exist")
        body = p.read_text(encoding="utf-8")
        for section in ("## Contract", "## Current state", "## Changelog"):
            if section not in body:
                errors.append(f"{rel}: missing section '{section}'")
        if len(body.splitlines()) > MAX_LINES:
            warns.append(f"{rel}: over {MAX_LINES} lines, trim the Changelog or split the node")
        for t in as_list(n.get("feeds")):
            if t in nodes and nid not in as_list(nodes[t].get("depends_on")):
                warns.append(f"{rel}: feeds '{t}' but '{t}' does not list '{nid}' in depends_on")

    for did, d in decisions.items():
        for nref in as_list(d.get("nodes")):
            if nref not in nodes:
                errors.append(f"{d['_path'].relative_to(ROOT)}: references unknown node '{nref}'")  # type: ignore[union-attr]

    text = GRAPH.read_text(encoding="utf-8") if GRAPH.exists() else ""
    m = re.search(re.escape(START) + r".*?" + re.escape(END), text, re.S)
    if not m:
        errors.append("context/GRAPH.md: generated block missing, run build")
    elif m.group(0) != render(nodes):
        errors.append("context/GRAPH.md: generated block is stale, run build")

    if not STATE.exists() or "## Handoff" not in STATE.read_text(encoding="utf-8"):
        errors.append("context/STATE.md: missing or has no '## Handoff' section")

    for w in warns:
        print(f"warn:  {w}")
    for e in errors:
        print(f"error: {e}")
    print(f"{len(nodes)} nodes, {len(decisions)} decisions, {len(errors)} errors, {len(warns)} warnings")
    return 1 if errors else 0


def read(nid: str) -> int:
    nodes = load_nodes()
    if nid not in nodes:
        print(f"unknown node '{nid}'. Known: {', '.join(sorted(nodes))}")
        return 1
    n = nodes[nid]
    files = ["context/STATE.md", f"context/nodes/{nid}.md"]
    for nb in sorted(set(as_list(n.get("depends_on")) + as_list(n.get("feeds")))):
        files.append(f"context/nodes/{nb}.md  (neighbour: read Contract only)")
    decisions = load_decisions()
    for d in as_list(n.get("decisions")):
        if d in decisions:
            files.append(str(decisions[d]["_path"].relative_to(ROOT)))  # type: ignore[union-attr]
    files.append(f"{n.get('code')}  (code)")
    print("\n".join(files))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "build":
        return build()
    if len(argv) >= 2 and argv[1] == "check":
        return check()
    if len(argv) >= 3 and argv[1] == "read":
        return read(argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
