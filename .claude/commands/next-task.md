---
description: Pick up the next task from STATE.md and implement it end to end
---

1. Run the `/context-load` steps for the next unchecked task in `context/STATE.md`.
2. Write a short plan and the tests that prove the task's acceptance criteria.
3. Implement in small steps. Run `uv run pytest -q`, `uv run ruff check .`, and `uv run mypy app` until green.
4. Run the `/context-sync` steps.
5. Stop and summarize. Do not start the following task.
