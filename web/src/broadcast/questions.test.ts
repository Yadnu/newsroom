import { expect, test } from "vitest";

import type { CallerQuestionEvent } from "@/lib/player";

import { type AskAction, IDLE, answerLineAt, askReducer, declineNote, isBusy, questionsUrl } from "./questions";

const Q: CallerQuestionEvent = {
  type: "caller_question",
  id: "q1",
  transcript: "when does nova ship",
  intent: "follow_up",
  story_id: "s1",
  story_title: "Acme Nova",
  restated: "When does Acme ship Nova?",
  allowed: true,
  screen_category: "ok",
  screen_reason: "",
};

const run = (...actions: AskAction[]) => actions.reduce(askReducer, IDLE);

test("a spoken question: listening, interims, checking, thinking, answering, done", () => {
  let s = run({ type: "listening" }, { type: "caller_interim", text: "when does" });
  expect([s.status, s.heard]).toEqual(["listening", "when does"]);
  s = askReducer(s, Q);
  expect([s.status, s.heard]).toEqual(["checking", "when does nova ship"]);
  s = askReducer(s, { type: "answer_status", question_id: "q1", state: "thinking" });
  expect(s.status).toBe("thinking");
  s = askReducer(s, {
    type: "answer_status",
    question_id: "q1",
    state: "answering",
    lines: [{ line_id: "a", text: "Nova ships in March.", start_ms: 0, end_ms: 900 }],
    audio_url: "/media/answers/q1.wav",
    duration_ms: 900,
  });
  expect(s.status).toBe("answering");
  expect(s.answer).toMatchObject({ audioUrl: "/media/answers/q1.wav", durationMs: 900, unsure: false });
  expect(isBusy(s)).toBe(true);
  s = askReducer(s, { type: "answer_done" });
  expect(isBusy(s)).toBe(false);
  expect(s.answer?.lines[0].text).toBe("Nova ships in March."); // stays readable after it played
});

test("declined and failed questions free the player with a note", () => {
  const off = { ...Q, intent: "off_topic" as const };
  let s = run({ type: "sent", text: "weather?" }, off, {
    type: "answer_status",
    question_id: "q1",
    state: "declined",
  });
  expect([s.status, s.note]).toEqual(["idle", "That is outside this story. Ask about the story on air."]);
  s = run({ type: "sent", text: "x" }, Q, { type: "answer_status", question_id: "q1", state: "failed" });
  expect(s.status).toBe("idle");
  expect(s.note).toMatch(/broadcast continues/);
  expect(declineNote({ ...Q, allowed: false, screen_category: "injection" })).toMatch(/instructions/);
});

test("an unvoiced answer is shown long enough to read; stale answers are ignored", () => {
  let s = run({ type: "sent", text: "x" }, Q);
  const stale = askReducer(s, { type: "answer_status", question_id: "old", state: "failed" });
  expect(stale).toBe(s);
  s = askReducer(s, {
    type: "answer_status",
    question_id: "q1",
    state: "unsure",
    lines: [{ line_id: "a", text: "I can't confirm more on that.", start_ms: null, end_ms: null }],
    audio_url: null,
    duration_ms: null,
  });
  expect(s.answer).toMatchObject({ audioUrl: null, unsure: true, durationMs: 3000 });
});

test("errors and a dropped socket end the question", () => {
  expect(run({ type: "listening" }, { type: "caller_error", message: "speech-to-text is not configured" })).toEqual({
    ...IDLE,
    note: "speech-to-text is not configured",
  });
  expect(run({ type: "listening" }, { type: "closed" }).note).toMatch(/Lost the connection/);
  expect(run({ type: "closed" })).toBe(IDLE);
});

test("answerLineAt follows the answer audio", () => {
  const lines = [
    { line_id: "a", text: "one", start_ms: 0, end_ms: 900 },
    { line_id: "b", text: "two", start_ms: 1200, end_ms: 2000 },
  ];
  expect(answerLineAt(lines, 100)?.line_id).toBe("a");
  expect(answerLineAt(lines, 1500)?.line_id).toBe("b");
  expect(answerLineAt([{ line_id: "c", text: "x", start_ms: null, end_ms: null }], 0)).toBeNull();
});

test("questionsUrl", () => {
  expect(questionsUrl("ws://localhost:8000/", "t 1")).toBe("ws://localhost:8000/press/telecasts/t%201/questions");
});
