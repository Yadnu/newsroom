---
id: caller
type: component
status: in-progress
phase: 5
code: app/caller/
depends_on: [archive, llm-gateway, standards-desk]
feeds: [standards-desk, producer, anchor]
decisions: [0004, 0018, 0019]
---

# caller

Voice input. Streams listener audio to text and classifies intent.

## Contract

- `async def listen(audio: AsyncIterator[bytes], context: CallerContext, *, stt=None, settings=None, classifier=None)
  -> AsyncIterator[CallerEvent]` (`pipeline.py`): PCM16 mono at `caller_sample_rate` (16 kHz) through a Pipecat STT
  pipeline. Yields `Interim(text)` while the listener talks and a `CallerQuestion` per utterance.
- An utterance ends after `caller_utterance_gap_ms` (800) with no new final transcript, when the audio ends
  (push-to-talk released: 0.3 s settle once the finals cover the audio sent, judged by the STT's segment timing
  when it gives one, else up to `caller_finalize_wait_ms` 1500), or at
  `caller_max_question_s` (30) of audio. Audio is held until the STT socket is open (`stt_ready`).
- `CallerQuestion(transcript, intent, story_id, restated, screen: ScreenResult | None, id, at)`; every question is
  screened by `standards_desk.screen_caller(transcript, intent)` after `classify()` (injectable `screener=`); intent `follow_up | background | off_topic |
  unknown` (unknown = the classify call failed).
- `async def classify(transcript, context) -> Intent(intent, story_id, restated)` (`intent.py`): llm-gateway `classify`
  route with `prompts/caller/classify_system.md` (static) and `classify_user.md` (stories as `S<n>` with title and
  what was heard, the story being read, the escaped transcript in `<question>`). Under 2 words: `off_topic`, no call.
- `CallerContext(briefing_id, stories: tuple[StoryRef(id, title, heard)], current_story_id)`;
  `async def context_for(script: ClearedScript, current_story_id=None)` (`context.py`).
- `make_stt(settings)` (`stt.py`): `caller_stt` = `deepgram` (`deepgram_api_key`, `deepgram_model` nova-3) or `fake`
  (`FakeSTTService(phrases)`: scripted words as audio arrives). `CallerConfigError` without a key.
- `CallIn` (`live.py`): push-to-talk on the Anchor WebSocket. Client `mic_start{sample_rate}`, binary PCM16 chunks,
  `mic_end`; server `caller_interim{text}`, `caller_question{id, transcript, intent, story_id, story_title, restated}`,
  `caller_error{message}`; `caller_question` also carries `allowed`, `screen_category`, `screen_reason`. One question
  at a time; the current story is the line being read at `mic_start`. `CallIn(on_question=...)` hands each
  question to the Producer (`handle_question`, task 5.3); a new mic_start waits until the answer is done.
- CLI `newsroom ask --briefing <id> --wav q.wav [--realtime]`.

## Invariants

- STT provider sits behind an adapter selected by config (decision 0004).
- Raw audio is not stored or logged; spans carry audio_ms and the transcript only.
- The transcript is untrusted: it goes escaped into the user turn of the classify prompt, never a system prompt.

## Current state

Task 5.1 done in `app/caller/`. Spans `caller/listen` (audio_ms, questions, interims, capped), `caller/question`
(transcript, intent, story_id, stt_ms), `caller/classify`. Tests: `tests/test_caller_listen.py`,
`tests/test_caller_intent.py`, mic route tests in `tests/test_anchor_routes.py`. Live 2026-11-19 (Deepgram nova-3,
`gpt-oss-20b`) on briefing `3873a08c`: a Cartesia-spoken "What did Satya Nadella say about Nvidia's interim chief?"
transcribed word for word and classified `follow_up` on the Nvidia/Altman story; "book me a table" was `off_topic`.
Over the live WebSocket: interim words while talking, question card 1.9 s after release. Two fixes came from the live
run: titles alone made the Nadella question `off_topic` (now each story carries what was heard), and audio sent
before Deepgram's socket opened lost the first word (now held by `stt_ready`). Answering is task 5.3.
Task 5.2: questions carry the Standards Desk screen; `listen.py` renamed `pipeline.py` (the module name shadowed the
`listen` function). A third live fix: settling 0.3 s after the first final cut transcripts when audio arrived faster
than real time ("What did..." became "What"), so the settle now waits until the finals cover the audio.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-19: Deepgram + fake STT, intent classification, push-to-talk on the Anchor WebSocket (task 5.1, decision 0018).
- 2026-11-19: questions screened by the Standards Desk; settle waits for finals to cover the audio (task 5.2).
- 2026-11-19: `CallIn` hands questions to the Producer for an on-air answer (task 5.3).
