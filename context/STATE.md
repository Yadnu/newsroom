# STATE

Last updated: 2026-11-16 by: Claude Code

## Current phase

Phase 1: Reporter and data layer

## Active task

1.3 archive (minimal): `span()` writing to `traces`, used by everything from here on

## Tasks

### Phase 0: bootstrap
- [x] 0.1 Scaffold the repo: uv project, folder per node, docker-compose (Postgres + pgvector, Redis), ruff, mypy, pytest, pre-commit, GitHub Actions CI
- [x] 0.2 `app/config.py` (pydantic-settings), `.env.example`, structlog setup, `/health` endpoint

### Phase 1: Reporter and data layer
- [x] 1.1 data-model: SQLModel models for all 8 tables + first Alembic migration + HNSW index
- [x] 1.2 llm-gateway: `complete()` with structured output, `embed()`, routing table, cost and token accounting
- [ ] 1.3 archive (minimal): `span()` writing to `traces`, used by everything from here on
- [ ] 1.4 reporter: RSS ingest with dedupe by URL and content_hash, scheduled job
- [ ] 1.5 reporter: clustering into stories by embedding similarity
- [ ] 1.6 CLI `newsroom stories --top 10` (acceptance: today's top 10 stories, each with 2+ sources)

### Phase 2: Writer and Editor (text only)
- [ ] 2.0 producer: simple `build_rundown()` (top N fresh stories, even time split)
- [ ] 2.1 writer: `draft_script()` with claim tagging, prompts in `prompts/`
- [ ] 2.2 editor: retrieval of evidence passages + `judge_claim()` with the 5-check rubric
- [ ] 2.3 rewrite loop: rejected claims go back to Writer, max 2 rounds
- [ ] 2.4 evals v1: 100 labelled claims + 30 planted falsehoods, `evals/run_evals.py` (acceptance: catch rate recorded)
- [ ] 2.5 CLI `newsroom brief --minutes 3` prints a script with verdict and source per claim

### Phase 3: Archive
- [ ] 3.1 `claim_trace()` API + rejection log API
- [ ] 3.2 Langfuse integration in llm-gateway
- [ ] 3.3 web: Archive dashboard (acceptance: any sentence traces to its source URL in one click)

### Phase 4: Anchor (voice out)
- [ ] 4.1 standards-desk: `clear_for_air()` and the `ClearedScript` type gate
- [ ] 4.2 anchor: Pipecat pipeline, Cartesia adapter, per-line audio timestamps
- [ ] 4.3 web: Player with synced, clickable transcript (acceptance: briefing plays in browser)

### Phase 5: Caller and Producer (voice in)
- [ ] 5.1 caller: Deepgram adapter, intent classification
- [ ] 5.2 standards-desk: `screen_caller()`
- [ ] 5.3 producer: rundown builder + barge-in handling + fast answer loop with latency budget
- [ ] 5.4 reporter: `search_live()` with Tavily/Exa + Firecrawl (acceptance: spoken follow-up gets a sourced answer, then the briefing resumes)

### Phase 6: Evals and polish
- [ ] 6.1 red team set (satire, stale, prompt injection), eval run in CI
- [ ] 6.2 correction pipeline: source retraction flags affected briefings
- [ ] 6.3 contradiction detection in Editor
- [ ] 6.4 README: architecture diagram, demo GIF, eval numbers, latency p50 and p95

## Open questions (defaults in use until answered)

- Topic scope for v1. Default: AI and tech news.
- One anchor voice or two. Default: one.
- Personalized rundowns. Default: same rundown for everyone in v1.

## Latest eval numbers

(none yet)

## Handoff

- Who worked last: Claude Code
- Done: 1.2. `complete()`/`embed()` in `app/shared/llm/`. Chat goes to Groq gpt-oss-20b, and the judge to gpt-oss-120b, with strict json_schema (decision 0008). Embeddings go to Voyage over httpx. Routing, retries, and cost/latency are logged as the `llm.call` event. 18 tests use a mock transport.
- Half done: no live Groq/Voyage call yet, since no keys are in `.env`. `docker compose up -d` is still unverified. There is no git remote, so CI has not run.
- Next: task 1.3. Build `span()`, then wrap the gateway calls so `Usage` reaches `traces` (tokens_in/out, cost_usd, latency_ms).
