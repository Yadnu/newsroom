# STATE

Last updated: 2026-11-23 by: Claude Code

## Current phase

Phase 7: hardening. Phases 0 to 6 are complete.

## Active task

None: 7.1 is done. Open items are in the handoff below.

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
- [x] 5.3 producer: rundown builder + barge-in handling + fast answer loop with latency budget
- [x] 5.4 reporter: `search_live()` with Tavily/Exa + Firecrawl (acceptance: spoken follow-up gets a sourced answer, then the briefing resumes)

### Phase 6: Evals and polish
- [x] 6.1 red team set (satire, stale, prompt injection), eval run in CI
- [x] 6.2 correction pipeline: source retraction flags affected briefings
- [x] 6.3 contradiction detection in Editor
- [x] 6.4 README: architecture diagram, demo GIF, eval numbers, latency p50 and p95

### Phase 7: hardening
- [x] 7.1 second judge provider: OpenRouter fallback for gpt-oss-120b, 429 fails over at once

## Open questions (defaults in use until answered)

- Topic scope for v1. Default: AI and tech news.
- One anchor voice or two. Default: one.
- Personalized rundowns. Default: same rundown for everyone in v1.

## Latest eval numbers

- 2026-11-18, judge_v1 (130 cases), prompt `dad2a081`, `gpt-oss-120b`: catch rate 1.00 (30/30), precision 0.904,
  recall 0.971, false flag rate 0.113. Results in `evals/results/judge_v1-dad2a081.*`.
- 2026-11-20, judge_v1, prompt `30f59e69` (satire line added): 120/130 judged (10 rate-limited), catch rate 1.00
  (27/27), precision 0.881, recall 0.952, false flag rate 0.138 (8, all over-strict attributed/corroborated).
- 2026-11-20, redteam_v1 (`evals/results/redteam_v1-3a4b8d4c.*`): clear rules 22/24 attacks, 0/9 false blocks
  (2 known gaps); screen rules pass all gated cases; full screen 27/28 attacks, 1/15 benign blocked; judge 15/15
  attacks, 2/5 controls flagged.
- 2026-11-23, judge_v1 (130/130), prompt `ca7ed1b1` (6 checks): catch rate 1.00 (30/30), precision 0.904, recall
  0.971, false flag rate 0.113; 107 cases answered by OpenRouter after a Groq 429 (decision 0025).
- 2026-11-23, contradictions_v1 (28/28), prompt `ca7ed1b1`: contradiction catch 1.00 (12/12), attributed
  disagreements 6/6 approved, precision 0.706, false flag rate 0.313 (5/16, all over-strict `attributed`).

## Handoff

- Who worked last: Claude Code
- Done: 7.1. The gateway knows a second chat host: `openrouter:<model id>` goes to OpenRouter. The judge falls back to the same `gpt-oss-120b` there when Groq fails, and with a usable fallback a 429 fails over at once instead of ~75 s of retries (decision 0025). The judge eval records the answering model per case. Branch `phase7/judge-fallback` stacks on #29, #28, #27, #25, #24; none merged.
- Open: OpenRouter key set and checked live: a direct probe judged 3/3 eval cases in strict JSON (3-5 s), and the full judge_v1 and contradictions_v1 runs completed with no pending cases. Over-strict `attributed` is the main false flag. Latency samples are small. Recheck has no schedule. Live search waits for Tavily/Firecrawl keys. Evals and Brief workflows need repo secrets (Groq and OpenRouter keys). Langfuse untested live.
- Next: schedule the retraction recheck (7.2).
