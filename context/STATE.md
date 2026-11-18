# STATE

Last updated: 2026-11-18 by: Claude Code

## Current phase

Phase 2: Writer and Editor (text only). Phase 1 is complete except the 1.6 acceptance run.

## Active task

2.4 evals v1: 100 labelled claims + 30 planted falsehoods, `evals/run_evals.py`

## Tasks

### Phase 0: bootstrap
- [x] 0.1 Scaffold the repo: uv project, folder per node, docker-compose (Postgres + pgvector, Redis), ruff, mypy, pytest, pre-commit, GitHub Actions CI
- [x] 0.2 `app/config.py` (pydantic-settings), `.env.example`, structlog setup, `/health` endpoint

### Phase 1: Reporter and data layer
- [x] 1.1 data-model: SQLModel models for all 8 tables + first Alembic migration + HNSW index
- [x] 1.2 llm-gateway: `complete()` with structured output, `embed()`, routing table, cost and token accounting
- [x] 1.3 archive (minimal): `span()` writing to `traces`, used by everything from here on
- [x] 1.4 reporter: RSS ingest with dedupe by URL and content_hash, scheduled job
- [x] 1.5 reporter: clustering into stories by embedding similarity
- [ ] 1.6 CLI `newsroom stories --top 10` (acceptance: today's top 10 stories, each with 2+ sources). Code done; acceptance run blocked on the Voyage key.

### Phase 2: Writer and Editor (text only)
- [x] 2.0 producer: simple `build_rundown()` (top N fresh stories, even time split)
- [x] 2.1 writer: `draft_script()` with claim tagging, prompts in `prompts/`
- [x] 2.2 editor: retrieval of evidence passages + `judge_claim()` with the 5-check rubric
- [x] 2.3 rewrite loop: rejected claims go back to Writer, max 2 rounds
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
- Done: 2.3. `editor.review_script()` judges, sends lines with non-approved claims to `writer.rewrite_line()` with the Editor's reasons, and re-judges, for at most 2 rounds. A rewrite replaces the line's claims, and the rejection history lives in `judge_claim` spans (decision 0013). The draft prompt now requires attribution. Branch `phase2/rewrite-loop`, stacked on `phase2/editor-judge`. 147 tests pass, including Neon integration.
- Half done: live Groq runs are flaky. `gpt-oss-20b` sometimes fails strict JSON twice (`StructuredOutputError`, which aborts all of `draft_script`), and rate limits cause retries of up to 26 s. Voyage key still missing (1.6 acceptance, live retrieval). Env: Neon Postgres + Upstash Redis + Groq in `.env`. Smart App Control blocks the SQLAlchemy `.pyd` files and the mypy exe: use `python -m mypy app` and the pure-Python `_cy` loader.
- Next: task 2.4. Build the eval set (100 labelled claims + 30 planted falsehoods), with `evals/run_evals.py` calling `judge_all()` over fixed passages, and record the catch rate in the editor node.
