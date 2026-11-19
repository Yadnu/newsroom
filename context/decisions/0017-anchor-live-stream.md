---
id: "0017"
title: Anchor streams live over a WebSocket (PCM + JSON events), timed on the audio clock
status: accepted
date: 2026-11-19
nodes: [anchor, web]
---

# 0017: Anchor streams live over a WebSocket (PCM + JSON events), timed on the audio clock

## Context
Task 4.2 voices a cleared script. The user chose live streaming through Pipecat now (not a pre-rendered file) so
barge-in (5.3) reuses the same path. The Player (4.3) needs audio plus a way to highlight the sentence being read,
and the Archive needs `audio_start_ms`/`audio_end_ms` per line.

## Decision
`speak(ClearedScript, VoiceSession)` runs a Pipecat 1.16 pipeline (TTS service -> our `_Airing` processor) and feeds
one `TTSSpeakFrame` per line, waiting for its `TTSStoppedFrame`. Timestamps come from the audio clock (PCM samples
sent / sample rate) with `anchor_line_gap_ms` of silence between lines, so they match the audio exactly. Realtime
sessions are paced to that clock in 20 ms slices (`anchor_send_ahead_ms` buffer). The web protocol is our own:
binary WebSocket messages are PCM16 mono chunks, text messages are JSON events (`start`, `line`, `line_end`,
`paused`, `resumed`, `done`); the client sends `pause`/`resume`. Default voice: Cartesia "Quentin - Refined Narrator".

## Alternatives considered
- Pipecat's FastAPI websocket transport with a serializer: built for conversational bots (RTVI, turn tracking); a
  plain PCM + JSON protocol is simpler for a browser player and keeps line events in order with the audio.
- Wall-clock timestamps: drift with network and TTS speed, and do not match the audio a player seeks in.
- Word timestamps from Cartesia: finer than needed for line highlighting; kept for later (karaoke-style).

## Consequences
Each airing rewrites the line timestamps with its own timeline (an interrupted live session includes the cut audio).
A pause drops queued audio within one 20 ms slice and replays the line on resume. Cartesia cost is not yet in
`llm_prices`; spans record characters spoken. Pipecat's loguru output is limited to warnings.
