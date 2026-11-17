# Newsroom

A voice-first AI news anchor: it fetches live news, writes a broadcast script, fact-checks every
claim against its sources with an LLM judge, and reads the brief aloud. Listeners can interrupt
with spoken questions and get a sourced answer.

Status: Phase 0 (bootstrap). See `context/STATE.md` for progress and `AGENTS.md` for the rules.

## Run

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker.

```bash
docker compose up -d        # Postgres 16 + pgvector, Redis 7
uv sync                     # install dependencies
uv run pytest -q            # tests
uv run ruff check . && uv run ruff format --check .
uv run mypy app
python scripts/context_graph.py check
```
