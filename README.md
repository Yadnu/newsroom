# Newsroom

A voice-first AI news anchor. It fetches live news, writes a broadcast script, fact-checks every
claim against its sources with an LLM judge, and reads the brief aloud. Listeners interrupt with a
spoken question, get a sourced answer, and the briefing resumes.

The rule the whole system is built around: **no sentence reaches the Anchor unless every claim in it
has `verdict = approved` and at least one stored evidence passage.** The Standards Desk enforces it
with a type (`ClearedScript`) that only `clear_for_air()` can build, and the Archive traces any
spoken sentence back to its source URL in one click.

![Demo: the Archive traces a sentence to its sources; the Player reads the briefing](docs/demo.gif)

A briefing built from the day's RSS feeds on 2026-11-23: the briefing list, the script with a verdict dot
per sentence, two sentences traced to their sources, and the Player. Grey dots are claims still
`pending` (the judge hit the Groq free-tier rate limit), which the Standards Desk keeps off air.

## Architecture

Each box is a folder under `app/` (the web app is `web/`). Solid arrows are the briefing path,
dotted arrows the live question path.

```mermaid
flowchart LR
  feeds[(RSS feeds)] --> reporter
  search[(Tavily + Firecrawl)] -.-> reporter
  reporter["Reporter<br/>ingest, dedupe, cluster,<br/>live search, retractions"] --> producer
  producer["Producer<br/>rundown, barge-in,<br/>answer loop"] --> writer
  writer["Writer<br/>script + claim tags"] --> editor
  editor["Editor<br/>LLM judge per claim,<br/>6 checks, rewrite loop"] -- rewrite --> writer
  editor --> desk["Standards Desk<br/>clear_for_air(),<br/>screen_caller()"]
  desk --> anchor["Anchor<br/>Pipecat + Cartesia TTS"]
  anchor --> listener((listener))
  listener -. speech .-> caller["Caller<br/>Deepgram STT,<br/>intent"]
  caller -.-> desk
  caller -.-> producer
  db[(Postgres + pgvector)] --- reporter
  db --- editor
  archive["Archive<br/>spans, claim trace,<br/>rejections, corrections"] --> web["Web<br/>Archive dashboard + Player"]
  anchor --> web
```

- **Reporter** pulls RSS, dedupes by URL and content hash, embeds (Voyage) and clusters sources into
  stories. For questions it searches the live web. `newsroom retract` / `recheck` mark withdrawn
  sources and record corrections.
- **Producer** picks the top fresh stories and splits the time, handles barge-in, and runs the
  answer loop inside a latency budget (a safe line is spoken if the budget runs out).
- **Writer** drafts the script and tags every factual claim with the sources it came from.
- **Editor** retrieves evidence passages for each claim (pgvector, cited and non-retracted sources
  only) and an LLM judge answers six checks: supported, faithful, attributed, fresh, corroborated
  (sensitive claims need two outlets) and consistent (sources disagree). Failed claims go back to the
  Writer for up to two rewrite rounds.
- **Standards Desk** clears lines for air (approved claims with evidence, no injected instructions,
  numbers and names traceable to evidence) and screens callers' questions. Corrections for retracted
  sources air first, from a fixed template.
- **Anchor** voices cleared lines with Cartesia through Pipecat and records per-line audio timestamps.
- **Caller** transcribes questions with Deepgram and classifies the intent.
- **Archive** records a span for every step (latency, tokens, cost) in Postgres, and serves the
  claim trace, rejection log and corrections. LLM calls also go to Langfuse when configured.

Every LLM call goes through one gateway (`app/shared/llm/`) with routing, retries, structured output
and cost accounting. Fetched web content is treated as data and never goes into a system prompt.
Design decisions are in [`context/decisions/`](context/decisions/).

## Eval numbers

Judge model `openai/gpt-oss-120b` on Groq. A claim is *flagged* when the judge does not approve it.

| Eval | Prompt | Result |
| --- | --- | --- |
| `judge_v1`: 100 labelled claims + 30 planted falsehoods | `dad2a081` | catch rate 1.00 (30/30), precision 0.904, recall 0.971, false flag rate 0.113 |
| `judge_v1` after the satire rule (120/130 judged, 10 rate-limited) | `30f59e69` | catch rate 1.00 (27/27), precision 0.881, recall 0.952, false flag rate 0.138 |
| `contradictions_v1`: 28 claims where outlets disagree (24 judged) | `ca7ed1b1` | contradicted claims caught 11/11, attributed disagreements approved 6/6, precision 0.786 |
| `redteam_v1`: Standards Desk rules (offline, gates CI) | - | 22/24 attacks blocked, 0/9 false blocks (2 known gaps) |
| `redteam_v1`: full caller screen (rules + LLM) | - | 27/28 attacks blocked, 1/15 harmless questions blocked |
| `redteam_v1`: judge on satire, stale and injected passages | `30f59e69` | 15/15 attacks caught, 2/5 controls flagged |

Most false flags are the judge asking for attribution on facts the outlets state plainly.
Results, per case, are in [`evals/results/`](evals/results/).

```bash
uv run python evals/run_evals.py                      # judge_v1 (resumes a partial run)
uv run python evals/run_evals.py --data evals/data/contradictions_v1.json
uv run python evals/run_redteam.py [--live]           # offline part runs in CI
```

## Latency

p50 and p95 per stage from the spans recorded on the dev database (`uv run python
evals/run_latency.py`, 2026-11-22). Sample sizes are small; the judge numbers include waits on the
Groq free tier's per-minute token limit: a judge call that goes through on the first attempt takes
p50 1.6 s, p95 2.0 s (n = 13).

| Path | Stage | n | p50 | p95 |
| --- | --- | --- | --- | --- |
| briefing | Fetch and dedupe RSS feeds | 5 | 2.0 s | 2.3 s |
| briefing | Write the script | 2 | 15.4 s | 19.2 s |
| briefing | Judge one claim | 50 | 22.3 s | 45.3 s |
| briefing | Judge every claim + rewrite loop | 2 | 172.7 s | 174.8 s |
| briefing | Clear for air | 24 | 634 ms | 802 ms |
| briefing | Voice one line (TTS) | 60 | 4.1 s | 6.8 s |
| answer | Classify + screen a question (after STT) | 17 | 1.1 s | 1.5 s |
| answer | Question to cleared answer | 2 | 9.8 s | 12.6 s |

## Run

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), Docker and Node 24 (what CI uses). Copy `.env.example` to
`.env` and fill in the keys you have (Groq, Voyage, Deepgram, Cartesia; Tavily and Firecrawl for
live search; OpenRouter optional, as the judge's fallback host when Groq rate-limits; Langfuse optional).

```bash
docker compose up -d db redis       # Postgres 16 + pgvector, Redis 7
uv sync                             # install dependencies
uv run alembic upgrade head         # create the schema
uv run newsroom stories --top 10    # ingest and cluster today's stories
uv run newsroom brief --minutes 3   # rundown, script, fact-check; prints each claim's verdict
uv run newsroom speak <briefing_id> --out brief.wav
uv run fastapi dev app/main.py      # API on :8000
cd web && npm ci && npm run dev     # Archive dashboard and Player on :3000
```

Other commands: `newsroom ask --briefing <id> --wav q.wav` (transcribe and classify a question),
`newsroom search "<question>"` (live web search), `newsroom retract <source id|url> --reason "..."`,
`newsroom recheck`, `newsroom corrections`.

## Develop

```bash
uv run pytest -q                    # tests
uv run ruff check . && uv run ruff format --check .
uv run mypy app
python scripts/context_graph.py check
```

Integration tests (`tests/integration/`) run when `NEWSROOM_TEST_DATABASE_URL` points at a
throwaway Postgres with pgvector; they wipe that database. Otherwise they are skipped.

Project memory for coding agents lives in [`context/`](context/): `STATE.md` (progress and handoff),
`GRAPH.md` (components and their edges) and one node file per component. Rules are in
[`AGENTS.md`](AGENTS.md).
