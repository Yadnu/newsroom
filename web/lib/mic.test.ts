import assert from "node:assert/strict";
import { test } from "node:test";

import { MicChunker, downsample, floatToPcm16 } from "./mic.ts";

test("float to pcm16 clips and rounds", () => {
  const v = new DataView(floatToPcm16(Float32Array.from([0, 1, -1, 2, -2, 0.5])));
  const got = Array.from({ length: 6 }, (_, i) => v.getInt16(i * 2, true));
  assert.deepEqual(got, [0, 32767, -32768, 32767, -32768, 16384]);
});

test("downsample 48k to 16k averages each group of three", () => {
  const out = downsample(Float32Array.from([0, 0.3, 0.6, 1, 1, 1, 0.5]), 48000, 16000);
  assert.equal(out.length, 2);
  assert.ok(Math.abs(out[0] - 0.3) < 1e-6 && out[1] === 1);
  const same = Float32Array.from([1, 2]);
  assert.equal(downsample(same, 16000), same); // same rate: passed through
  assert.throws(() => downsample(new Float32Array(4), 8000, 16000));
});

test("chunker emits 100 ms chunks at 16 kHz and keeps the remainder", () => {
  const c = new MicChunker(48000, 100); // 4800 input samples per chunk
  const frame = new Float32Array(128).fill(0.25);
  let chunks: ArrayBuffer[] = [];
  for (let i = 0; i < 40; i++) chunks = chunks.concat(c.push(frame)); // 5120 samples
  assert.equal(chunks.length, 1);
  assert.equal(chunks[0].byteLength, 1600 * 2); // 4800 / 3 samples at 16 kHz
  const rest = c.flush();
  assert.ok(rest && rest.byteLength === Math.floor(320 / 3) * 2);
  assert.equal(c.flush(), null);
});
