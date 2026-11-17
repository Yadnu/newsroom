---
description: Write work back into the context graph before stopping
---

Sync the context graph with what changed in this session.

1. Run `git diff --stat` and `git diff` to see what changed since the last commit (or since the session started).
2. For each touched component, update `context/nodes/<id>.md`: frontmatter `status` and `code`, `Contract` if the public surface changed, `Current state`, and add one dated line to `Changelog`.
3. If an architectural choice was made, create `context/decisions/NNNN-title.md` (next number) using the template in `context/decisions/0000-template.md`, and link it in the node's `decisions:`.
4. Update `context/STATE.md`: tick finished tasks, set the next task, and rewrite the Handoff section (who worked: Claude Code, what is done, what is half done, what to do next).
5. Run `python scripts/context_graph.py build` and `python scripts/context_graph.py check`. Fix all errors.
6. Show the diff of `context/` and propose a commit message.
