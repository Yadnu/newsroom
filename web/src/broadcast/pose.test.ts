import { expect, test } from "vitest";

import { STILL, blinkAt, poseAt } from "./pose";

const SCRIPT = {
  audioOffset: 2500,
  nodAt: 20_000,
  captions: [
    { lineId: "a", text: "A", start: 2500, end: 8000, words: [], estimated: true },
    { lineId: "b", text: "B", start: 8300, end: 20_000, words: [], estimated: true },
  ],
};

test("the same moment always gives the same pose (seek-safe)", () => {
  expect(poseAt(SCRIPT, 12_345)).toEqual(poseAt(SCRIPT, 12_345));
});

test("looks at the papers in the bumper, up while speaking, down again after signing off", () => {
  expect(poseAt(SCRIPT, 500).lookDown).toBe(1);
  expect(poseAt(SCRIPT, 6000).lookDown).toBe(0);
  expect(poseAt(SCRIPT, 20_000 + 1200 + 900).lookDown).toBe(1);
});

test("nods as the last line ends", () => {
  const before = poseAt(SCRIPT, 19_900).headPitch;
  const nod = poseAt(SCRIPT, 20_350).headPitch;
  expect(nod - before).toBeGreaterThan(5);
});

test("raises the brows as each line starts", () => {
  expect(poseAt(SCRIPT, 8300 + 300).brow).toBeGreaterThan(0.7);
  expect(poseAt(SCRIPT, 12_000).brow).toBe(0);
});

test("blinks briefly, every few seconds", () => {
  let shut = 0;
  for (let t = 0; t < 60_000; t += 10) if (blinkAt(t) > 0.5) shut += 10;
  const blinks = shut / 100; // ~100 ms of each 160 ms blink is past half-shut
  expect(blinks).toBeGreaterThan(10);
  expect(blinks).toBeLessThan(24);
  expect(blinkAt(0)).toBe(0);
});

test("reduced motion: a still pose, only the look at the papers switches", () => {
  expect(poseAt(SCRIPT, 6000, true)).toEqual(STILL);
  expect(poseAt(SCRIPT, 500, true)).toEqual({ ...STILL, lookDown: 1 });
});
