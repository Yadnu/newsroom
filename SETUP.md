# Newsroom agent kit: setup

## What is in the kit

```
AGENTS.md                  rules + stack + commands: the single source of truth
CLAUDE.md                  Claude Code entry point; imports AGENTS.md, STATE.md, GRAPH.md
DEVELOPMENT_PROMPT.md      paste once to start the project
.cursor/rules/*.mdc        Cursor rules: 1 always-on core rule + 6 rules scoped by file globs
.cursor/commands/          /context-load, /context-sync, /next-task for Cursor
.claude/commands/          the same three commands for Claude Code
context/GRAPH.md           graph index (generated block: nodes table + mermaid diagram)
context/STATE.md           phase, task checklist, open questions, handoff note
context/nodes/*.md         one file per component: Contract, Invariants, Current state, Changelog
context/decisions/*.md     architecture decision records
scripts/context_graph.py   build | check | read <node>  (standard library only)
.pre-commit-config.yaml    blocks commits when the graph is broken or stale
```

## Install

1. Create the repo (`mkdir newsroom && cd newsroom && git init`) and copy the kit's contents into its root.
   Keep the dot folders (`.cursor`, `.claude`).
2. `python scripts/context_graph.py check` should print 0 errors.
3. `pip install pre-commit && pre-commit autoupdate && pre-commit install`.
4. Commit: `git add -A && git commit -m "chore: agent kit and context graph"`.
5. Open the repo in Cursor or Claude Code and paste `DEVELOPMENT_PROMPT.md` (below its line).

## How the two tools share one brain

| | Claude Code | Cursor |
| --- | --- | --- |
| Rules loaded | `CLAUDE.md`, which imports `AGENTS.md`, `STATE.md`, `GRAPH.md` | `.cursor/rules/00-core.mdc` always; other rules when matching files are in play; `AGENTS.md` |
| Start a session | `/context-load <task or node>` | `/context-load` in Agent chat |
| Do the next task | `/next-task` | `/next-task` |
| End a session | `/context-sync` | `/context-sync` |

The handoff note in `context/STATE.md` is how one tool tells the other where it stopped.
Always end a session with `/context-sync` and a commit, then the other tool picks up cleanly.

## Suggested split

- **Claude Code:** multi-file features, refactors across nodes, running tests and evals in a loop, the
  context sync. It is better at long autonomous runs in the terminal.
- **Cursor:** focused edits inside one node, UI work in `web/`, reviewing diffs, quick fixes with tab completion.
- Never run both on the same task at the same time. Commit before switching.

## Keeping the graph useful

- Edges live in node frontmatter only. `build` regenerates `GRAPH.md`; `check` fails on stale or broken links.
- `python scripts/context_graph.py read editor` lists exactly which files to read for an Editor task.
- A Contract is a promise to other nodes. Change it only together with the code, and note it in the Changelog.
- Trim Changelogs past ~120 lines per node (the check warns). Old detail lives in git history.
- New component? Copy a node file, change the frontmatter, add its folder, run `build`.
- New decision? Copy `context/decisions/0000-template.md` to the next number and link it from the node.

## Why the rules are split this way

- One short always-on rule keeps every request cheap; the scoped rules only load for files they cover,
  so the LLM rules do not crowd a frontend task and the other way round.
- Rules state constraints the code must keep (gates, boundaries, where calls go). Style the linter
  already enforces is left out.
- `AGENTS.md` stays the only place to edit shared rules. The Cursor rules and `CLAUDE.md` point back to it,
  so the two tools cannot drift apart.
