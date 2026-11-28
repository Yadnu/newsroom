---
id: "0031"
title: Telecast questions go over their own WebSocket and are answered as short voiced files
status: accepted
date: 2026-11-27
nodes: [press, caller, web]
---

# 0031: Telecast questions go over their own WebSocket and are answered as short voiced files

## Context

Task 9.6: readers watching a telecast (a prerecorded MP3 the browser plays, decision 0027) should be able to ask
about the story by voice or by typing. Live briefings already take push-to-talk questions over the Anchor
WebSocket, where answers are spoken into the same PCM stream (decision 0020). A telecast has no live stream to speak
into, and the broadcast player's clock, captions and lip sync are built around an `<audio>` element.

## Decision

- WebSocket `/press/telecasts/{id}/questions`, opened by the browser on the first question. Typed questions are
  `{"type": "ask", "text"}`; spoken ones reuse the push-to-talk protocol and `caller.live.CallIn` unchanged. Only
  a `ready` telecast takes questions (4409 otherwise); its stored script is cleared again (`clear_stored`) so the
  Caller sees what the reader heard.
- Typed text goes through the same classify -> `screen_caller` path as a transcript (`caller.ask.question_from_text`).
- Answers use the Producer's `answer_question` (sources, Writer, Editor judge, `clear_for_air`, safe line), then are
  voiced to `media_dir/answers/<question id>.wav` and sent as `answer_status` with the lines, their audio timings and
  the URL. If voicing fails the answer still arrives, captions only. The browser pauses the telecast, plays the
  answer, then resumes if it was playing.
- Answer audio is not recorded on any row; `cleanup_media` removes it as an orphan after an hour.

## Alternatives considered

- Stream answer PCM over the socket and mix it with Web Audio: the player would need a second clock and the lip
  sync tap a second source, for answers that last a few seconds.
- POST for typed questions plus a socket for voice: two paths to keep in order, and "one question at a time" would
  need a server-side lock across them; one socket gets both from `CallIn`.
- Keeping answers with the telecast (a column or table): no reader returns to an answer; the Archive already has
  the answer lines and their verdicts under the telecast's briefing.

## Consequences

Answer lines are stored under the telecast's briefing (`kind = 'answer'`), so the telecast view now reads only
`kind = 'script'` lines and verdicts. Answers cost one LLM loop and a few seconds of TTS each; there is no
per-reader rate limit yet beyond one question at a time per socket.
