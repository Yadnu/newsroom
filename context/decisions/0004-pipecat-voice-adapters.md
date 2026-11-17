---
id: "0004"
title: Pipecat voice pipeline with swappable STT and TTS adapters
status: accepted
date: 2026-11-16
nodes: [anchor, caller]
---

# 0004: Pipecat voice pipeline with swappable STT and TTS adapters

## Context
Real-time voice needs streaming, barge-in, and low latency. Providers change fast.

## Decision
Pipecat runs the pipeline. Deepgram (STT) and Cartesia (TTS) sit behind adapters chosen by config.

## Alternatives considered
- LiveKit Agents: strong option, kept as the fallback if Pipecat transport limits appear.
- Hand-rolled WebSocket pipeline: too much work on plumbing instead of the product.

## Consequences
Provider swaps are config changes. The adapter interface must cover streaming and interruption.
