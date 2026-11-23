import assert from "node:assert/strict";
import { test } from "vitest";

import { AudioClock, activeLine, applyEvent, pcm16ToFloat32, wsBase } from "./player.ts";
import type { TimedLine } from "./player.ts";

test("pcm16 little-endian to floats", () => {
  const buf = new ArrayBuffer(6);
  const v = new DataView(buf);
  v.setInt16(0, 0, true);
  v.setInt16(2, 16384, true);
  v.setInt16(4, -32768, true);
  assert.deepEqual(Array.from(pcm16ToFloat32(buf)), [0, 0.5, -1]);
});

test("chunks are scheduled back to back and mapped to the audio clock", () => {
  const clock = new AudioClock(1000, 0.1); // 1 kHz keeps the numbers small
  assert.equal(clock.schedule(500, 0), 0.1); // 0.5 s chunk, starts after the lead
  assert.equal(clock.schedule(500, 0.2), 0.6); // contiguous
  assert.equal(clock.clockAt(0.05), null); // nothing playing yet
  assert.equal(clock.clockAt(0.35), 250);
  assert.equal(clock.clockAt(0.85), 750);
  assert.equal(clock.clockAt(5), 1000); // never ahead of what was received
});

test("after an underrun or a pause the next chunk starts a new segment", () => {
  const clock = new AudioClock(1000, 0.1);
  clock.schedule(500, 0); // plays 0.1 to 0.6, clock 0 to 500
  clock.reset(); // paused: the rest was dropped
  assert.equal(clock.schedule(500, 2), 2.1); // resumed at t=2
  assert.equal(clock.clockAt(2.35), 750);
  assert.equal(clock.clockAt(1.0), 500); // silence while paused: still at the end of what played
});

test("active line follows start and end events, replays restamp the line", () => {
  let lines: TimedLine[] = [];
  lines = applyEvent(lines, { type: "line", line_id: "a", order: 0, text: "A", start_ms: 0 });
  assert.equal(activeLine(lines, 100), "a");
  lines = applyEvent(lines, { type: "line_end", line_id: "a", end_ms: 900 });
  assert.equal(activeLine(lines, 950), null); // the gap between lines
  lines = applyEvent(lines, { type: "line", line_id: "b", order: 2, text: "B", start_ms: 1200 });
  assert.equal(activeLine(lines, 1300), "b");
  lines = applyEvent(lines, { type: "line", line_id: "b", order: 2, text: "B", start_ms: 1600 });
  assert.equal(lines.filter((l) => l.line_id === "b").length, 1);
  assert.equal(activeLine(lines, 1300), null);
});

test("ws base from the api url", () => {
  assert.equal(wsBase("http://localhost:8000/"), "ws://localhost:8000");
  assert.equal(wsBase("https://api.example.test"), "wss://api.example.test");
});
