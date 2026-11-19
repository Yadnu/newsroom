# STATE

Last updated: 2026-11-19 by: Claude Code

## Current phase

Phase 5: Caller and Producer (voice in). Phases 1 to 4 are complete.

## Active task

5.3 producer: rundown builder + barge-in handling + fast answer loop with latency budget

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
- [x] 1.6 CLI `newsroom stories --top 10` (acceptance: today's top 10 stories, each with 2+ sources)

### Phase 2: Writer and Editor (text only)
- [x] 2.0 producer: simple `build_rundown()` (top N fresh stories, even time split)
- [x] 2.1 writer: `draft_script()` with claim tagging, prompts in `prompts/`
- [x] 2.2 editor: retrieval of evidence passages + `judge_claim()` with the 5-check rubric
- [x] 2.3 rewrite loop: rejected claims go back to Writer, max 2 rounds
- [x] 2.4 evals v1: 100 labelled claims + 30 planted falsehoods, `evals/run_evals.py` (acceptance: catch rate recorded)
- [x] 2.5 CLI `newsroom brief --minutes 3` prints a script with verdict and source per claim

### Phase 3: Archive
- [x] 3.1 `claim_trace()` API + rejection log API
- [x] 3.2 Langfuse integration in llm-gateway
- [x] 3.3 web: Archive dashboard (acceptance: any sentence traces to its source URL in one click)

### Phase 4: Anchor (voice out)
- [x] 4.1 standards-desk: `clear_for_air()` and the `ClearedScript` type gate
- [x] 4.2 anchor: Pipecat pipeline, Cartesia adapter, per-line audio timestamps
- [x] 4.3 web: Player with synced, clickable transcript (acceptance: briefing plays in browser)

### Phase 5: Caller and Producer (voice in)
- [x] 5.1 caller: Deepgram adapter, intent classification
- [x] 5.2 standards-desk: `screen_caller()`
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

- 2026-11-18, judge_v1 (130 cases), prompt `dad2a081`, `gpt-oss-120b`: catch rate 1.00 (30/30), precision 0.904,
  recall 0.971, false flag rate 0.113. Results in `evals/results/judge_v1-dad2a081.*`.

## Handoff

- Who worked last: Claude Code
- Done: 5.2. `standards_desk.screen_caller()`: rules (injection, insults, empty, too long, off-topic intent) then LLM moderation on `gpt-oss-20b`, fail open on LLM errors (decision 0019); every Caller question carries the verdict and blocked ones show "not taken" in the Player. Live: 8/8 typed cases right, spoken injection blocked. Also fixed transcripts cut short when audio arrives faster than real time. Branch `phase5/screen-caller` stacks on #19 to #16; none merged.
- Open: Groq free tier 8000 TPM on the judge (half of claims `pending`, pending lines never air). Standards rules are heuristics (tune in 6.1 red team). Cartesia/Deepgram cost not tracked. In-browser mic use not automated here. Integration tests run only in CI. Test stories and a `draft` briefing `42c6f7d3` are in the dev DB. Brief workflow needs repo secrets. Langfuse untested live.
- Next: 5.3 producer: answer allowed questions fast (latency budget), auto-pause on speech (barge-in), resume the briefing.
