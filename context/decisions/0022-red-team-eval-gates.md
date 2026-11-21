---
id: "0022"
title: Red team eval - deterministic guardrails gate CI, LLM guardrails run live and are recorded
status: accepted
date: 2026-11-20
nodes: [standards-desk, editor]
---

# 0022: Red team eval - deterministic guardrails gate CI, LLM guardrails run live and are recorded

## Context
Task 6.1: satire, stale and prompt-injection cases against the three guardrails: the Editor's judge (LLM), the
Standards Desk's `clear_for_air` rules (deterministic) and the caller screen (rules, then LLM moderation). CI has no
Groq key (repo secrets are not set), and LLM verdicts vary run to run, so an LLM-scored gate would be flaky or skipped.

## Decision
One set, `evals/data/redteam_v1.json` (invented entities), three suites: `judge`, `screen`, `clear`.
`evals/run_redteam.py` runs offline by default: every `clear` case through `check_line` (the real rule code with the
stored state built from the case) and every `screen` case through `screen_rules`. Offline is a gate: it exits 1 if a
`clear` case or a `layer: rules` screen case is wrong, or if the rules block a benign question. It runs as a CI step
and as a pytest test. `known_gap` cases are reported, not gated. `--live` adds the full `screen_caller` and the
judge; it records results in `evals/results/redteam_v1-<prompt hash>.*` and never fails the run. A manual
`Evals` workflow runs it with the Groq secret.

## Alternatives considered
- Live LLM run on every PR: needs secrets in CI, costs quota on every push, and noise would make the gate flaky.
- Replay recorded LLM answers in CI: checks the scoring code, not the model or the prompt, and goes stale on every
  prompt change.

## Consequences
Rule changes in `screen.py` / `clear.py` must keep the offline gate green. LLM-layer numbers are only as fresh as
the last live run; they are recorded in STATE and the editor node after each prompt change.
