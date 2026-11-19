---
id: "0018"
title: Caller v1 is push-to-talk over the Anchor WebSocket, classified by the gateway
status: accepted
date: 2026-11-19
nodes: [caller, anchor, web]
---

# 0018: Caller v1 is push-to-talk over the Anchor WebSocket, classified by the gateway

## Context
Task 5.1 turns listener speech into a classified question. The user chose to wire the browser mic in this task.
Automatic barge-in (voice activity pausing the Anchor) and answering are task 5.3. Speakers playing the briefing can
leak into an open mic, and Deepgram's live socket takes a moment to open.

## Decision
Push-to-talk: "Hold to ask" pauses the Anchor and streams 16 kHz PCM16 mic audio over the same WebSocket
(`mic_start`, binary chunks, `mic_end`); one question at a time. `caller.listen()` runs Pipecat's Deepgram service
(nova-3) and ends an utterance on an 800 ms gap with no new final transcript, on release (0.3 s settle once a final is
in, else up to 1.5 s), or at 30 s. Audio is held until the STT socket is open. Intent comes from the gateway's
`classify` route (`gpt-oss-20b`) with each story's title and what the Anchor said about it; the transcript is escaped
in the user turn.

## Alternatives considered
- Always-on mic with VAD barge-in now: needs echo handling against the Anchor's own audio; planned for 5.3.
- A separate WebSocket for the mic: two connections to keep in step; one socket keeps the current line known.
- Titles only as classifier context: live, a question about a person mentioned in a story came back `off_topic`.

## Consequences
Questions are typed only by intent and story for now; nothing answers them yet (5.3). Raw audio is never stored.
`stt_ready` waits on a private Pipecat attribute (`_connection_settled`); recheck it on Pipecat upgrades.
