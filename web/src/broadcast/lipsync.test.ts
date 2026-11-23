import { expect, test } from "vitest";

import { estimateWords, mouthAt, withAmplitude, wordAt } from "./lipsync";

const WORDS = [
  { text: "Mama", start: 0, end: 400 },
  { text: "oops!", start: 500, end: 1000 },
  { text: "2026", start: 1000, end: 1400 },
];

test("estimateWords spreads a line over its words by length, inside the line", () => {
  const w = estimateWords("Hi there, everyone", 1000, 3000);
  expect(w.map((x) => x.text)).toEqual(["Hi", "there,", "everyone"]);
  expect(w[0].start).toBe(1000);
  expect(w[w.length - 1].end).toBe(3000);
  expect(w[2].end - w[2].start).toBeGreaterThan(w[0].end - w[0].start);
  expect(estimateWords("", 0, 100)).toEqual([]);
  expect(estimateWords("x", 100, 100)).toEqual([]);
});

test("wordAt finds the spoken word and nothing in the gaps", () => {
  expect(wordAt(WORDS, 100)?.text).toBe("Mama");
  expect(wordAt(WORDS, 450)).toBeNull();
  expect(wordAt(WORDS, 1000)?.text).toBe("2026");
  expect(wordAt(WORDS, 5000)).toBeNull();
});

test("mouth shapes follow the letters, closed for m and at rest between words", () => {
  expect(mouthAt(WORDS, 10).shape).toBe("closed"); // M
  expect(mouthAt(WORDS, 150).shape).toBe("ah"); // a
  expect(mouthAt(WORDS, 450)).toEqual({ shape: "rest", open: 0 });
  expect(mouthAt(WORDS, 520).shape).toBe("oh"); // o
  expect(mouthAt(WORDS, 1200)).toEqual({ shape: "ee", open: 0.3 }); // digits
  const open = mouthAt(WORDS, 150).open;
  expect(open).toBeGreaterThan(0.5);
  expect(open).toBeLessThanOrEqual(1);
});

test("amplitude scales the opening but never opens a resting mouth", () => {
  const m = { shape: "ah" as const, open: 0.8 };
  expect(withAmplitude(m, null)).toEqual(m);
  expect(withAmplitude(m, 0).open).toBeCloseTo(0.28);
  expect(withAmplitude(m, 1).open).toBe(1);
  expect(withAmplitude({ shape: "rest", open: 0 }, 1)).toEqual({ shape: "rest", open: 0 });
});
