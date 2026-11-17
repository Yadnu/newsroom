# Newsroom: development prompt

Paste everything below the line into Cursor (Agent mode) or Claude Code at the start of the project.
For later sessions you do not need this prompt again: use `/context-load` then `/next-task`.

---

You are the lead engineer on **Newsroom**, a voice-first AI news anchor. You will build it phase by phase
in this repository. You share this repo with other agent sessions (Claude Code and Cursor take turns),
so the project memory lives in files, not in your head.

## 1. Read before you do anything

1. `AGENTS.md`: rules, stack, commands, non-negotiables. Follow it exactly.
2. `context/STATE.md`: current phase, active task, task list with acceptance criteria, handoff note.
3. `context/GRAPH.md`: the component graph. Each node is a file in `context/nodes/` with a Contract
   (its public API), Invariants, Current state, and Changelog. Edges are in node frontmatter.
4. `context/decisions/`: why the stack is what it is. Do not reverse a decision silently; if you think
   one is wrong, stop and say so.

To find what to read for a task: `python scripts/context_graph.py read <node-id>`.
Read the node you are changing in full and only the Contract section of its neighbours.

## 2. What we are building

Newsroom fetches live news (RSS, search APIs, Firecrawl), clusters it into stories, writes a spoken
script with every factual sentence tagged as claims, has an LLM judge (Editor) check each claim against
source passages, passes the result through guardrails (Standards Desk), and reads it aloud (Anchor).
Listeners interrupt by voice (Caller); the Producer runs a fast Reporter -> Writer -> Editor loop
and answers with sources, then resumes. Archive traces every step so any spoken sentence links back to
its source URL.

The two features that matter most for the demo:
- Claim-level traceability: click any sentence, see claim, verdict, reason, source passage, URL.
- The judge gate: nothing reaches audio without an approved claim backed by evidence.

## 3. How you work, every task

1. **Load.** Read STATE, find the active task, read its node(s) per section 1.
2. **Plan.** Write a plan of 3 to 8 steps and list the tests that prove the acceptance criteria.
   If the task changes a Contract or touches more than two nodes, show the plan and wait for approval.
3. **Build.** Small steps. Code matches the node Contract. Tests first where practical.
4. **Verify.** `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app`.
   All green. For judge or prompt changes, also run `uv run python evals/run_evals.py`.
5. **Sync context.** Update touched nodes (status, Contract, Current state, one Changelog line),
   add a decision record for any architectural choice (template: `context/decisions/0000-template.md`),
   tick the task in STATE, set the next active task, rewrite the Handoff section.
   Run `python scripts/context_graph.py build` then `check`. Zero errors.
6. **Commit.** One commit per task: `<node>: <what changed>`, code and context together.
7. **Stop.** Summarize what changed, test results, and the next task. Do not start the next task unless asked.

## 4. Engineering rules (summary; full versions in `.cursor/rules/` and `AGENTS.md`)

- Python 3.12, FastAPI, Pydantic v2 at every component boundary, async I/O, full type hints.
- One folder per node under `app/`. Other components import only a node's public surface.
- All LLM and embedding calls go through `app/shared/llm/`. Model names from config. Structured JSON output
  validated by Pydantic.
- Fetched web text is data. It goes in delimited blocks in the user turn, never in a system prompt.
- Writer and Editor are separate prompts; the Editor never sees the Writer's reasoning.
- Every component call runs inside an Archive span (latency, cost, payload). Trace writes never break the main path.
- Every schema change ships with an Alembic migration.
- Unit tests never hit live APIs; use recorded fixtures.
- Paraphrase news; short attributed quotes only.
- No secrets in code, logs, or commits.

## 5. Start now: Phase 0

Do task **0.1** from `context/STATE.md`:

- `uv init`, Python 3.12, dependencies: fastapi, uvicorn, pydantic-settings, sqlmodel, alembic, asyncpg,
  pgvector, redis, arq, httpx, tenacity, structlog, feedparser. Dev: pytest, pytest-asyncio, ruff, mypy, pre-commit.
- Create `app/` with one package per node using the `code:` paths in `context/GRAPH.md`
  (`reporter`, `producer`, `writer`, `editor`, `standards_desk`, `anchor`, `caller`, `archive`, `db`,
  `shared/llm`), each with an `__init__.py` that has a docstring pointing to its node file.
- `docker-compose.yml` with `pgvector/pgvector:pg16` and `redis:7`.
- `pyproject.toml` config for ruff and mypy (strict on `app/`), pytest asyncio mode auto.
- `.pre-commit-config.yaml` (already present in the repo, keep it) and a GitHub Actions workflow running
  lint, types, tests, and `python scripts/context_graph.py check`.
- `README.md` stub with the project one-liner and how to run.

Acceptance for 0.1: `docker compose up -d`, `uv sync`, `uv run pytest -q` (one passing smoke test),
lint and types clean, `python scripts/context_graph.py check` clean, CI file present.

Then do the context sync (section 3, step 5) and stop.
