# CLAUDE.md

@AGENTS.md
@context/STATE.md
@context/GRAPH.md

## Claude Code specifics

- Node files are not auto-loaded. Read the ones your task touches before editing code.
- Use `/context-load` at the start of a session and `/context-sync` before you stop.
- Use plan mode for any task that touches more than one node or changes a Contract.
- When a task is done, commit with message `<node>: <what changed>` and include the context file updates in the same commit.
- If Cursor worked last, the handoff note in `context/STATE.md` tells you where it stopped. Trust it, then verify with `git log -5`.
