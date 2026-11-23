---
id: "0028"
title: Word timings come from the TTS and are stored per line; the anchor animates as pure functions of show time
status: accepted
date: 2026-11-23
nodes: [anchor, press, web]
---

# 0028: Word timings come from the TTS and are stored per line; the anchor animates as pure functions of show time

## Context
Task 8.4: an animated anchor with lip sync and word-level captions in the telecast player. Audio had only
line-level timings. The plan (FRONTEND_PLAN.md) named GSAP for the broadcast timeline and an AnalyserNode
for lip sync when no timings exist.

## Decision
- Cartesia already streams word timestamps through Pipecat (`add_timestamps`). A subclass of the Pipecat service
  records them per TTS context; the fake TTS spaces words evenly. `speak()` turns them into absolute
  `(word, start_ms, end_ms)` spans on the audio clock (`LineTiming.words`, `word_spans()`) and stores them in
  `script_lines.audio_words` (JSONB). `TelecastLine.words` exposes them.
- The web player uses real word timings for word-highlighted captions and lip sync; a line without them gets
  estimated words (its duration spread by word length) and the mouth is then scaled by live loudness from a Web
  Audio analyser, tapped only once the AudioContext is running so it can never silence playback.
- Mouth shapes come from the letters of the current word (seven shapes, sine envelope per letter). No phoneme or
  viseme data is used.
- The anchor's pose (blinks on a seeded schedule, breathing, head tilts, looking at the papers before and after
  speaking, a nod as the last line ends, brows up as each line starts) is `poseAt(script, t)`, a pure function of
  show time. Rendering applies those numbers to a layered SVG. GSAP is not used: `ShowClock` already drives
  every component from one time value, so pause, seek, speed and replay need no second timeline.

## Alternatives considered
- GSAP timeline seeked from the clock: same result with another dependency and two sources of truth.
- Phoneme timestamps: not available through our Pipecat Cartesia adapter; letters are close enough for a
  stylized character.
- Amplitude-only lip sync: needs Web Audio routing (autoplay rules, muted audio reads as silence) and is
  noisier than word timings.

## Consequences
Telecasts voiced before this change have no word timings and fall back to estimates. Lip sync is approximate
(letters, not phonemes) and tuned for English.
