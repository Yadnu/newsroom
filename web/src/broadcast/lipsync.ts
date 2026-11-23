// Word timing and mouth shapes (task 8.4). Pure: everything is a function of show time.

export interface TimedWord {
  text: string;
  start: number;
  end: number;
}

/** Mouth shapes the anchor SVG draws. "rest" between words, "closed" for m/b/p. */
export type MouthShape = "rest" | "closed" | "ah" | "ee" | "oh" | "oo" | "fv";

export interface Mouth {
  shape: MouthShape;
  open: number; // 0..1, how far the jaw is open
}

const REST: Mouth = { shape: "rest", open: 0 };

/** Without TTS word timings, spread the line over its words by length (marked estimated upstream). */
export function estimateWords(text: string, start: number, end: number): TimedWord[] {
  const words = text.split(/\s+/).filter(Boolean);
  if (!words.length || end <= start) return [];
  const weights = words.map((w) => w.replace(/[^\p{L}\p{N}]/gu, "").length + 1);
  const total = weights.reduce((a, b) => a + b, 0);
  let at = start;
  return words.map((text, i) => {
    const span = ((end - start) * weights[i]) / total;
    const w = { text, start: Math.round(at), end: Math.round(at + span) };
    at += span;
    return w;
  });
}

function shapeOf(ch: string): MouthShape {
  if ("a".includes(ch)) return "ah";
  if ("eiy".includes(ch)) return "ee";
  if ("o".includes(ch)) return "oh";
  if ("uwq".includes(ch)) return "oo";
  if ("mbp".includes(ch)) return "closed";
  if ("fv".includes(ch)) return "fv";
  return "ee"; // other consonants: lips apart, teeth near
}

const OPENNESS: Record<MouthShape, number> = {
  rest: 0,
  closed: 0.05,
  ah: 1,
  oh: 0.8,
  oo: 0.45,
  ee: 0.5,
  fv: 0.25,
};

/** The word being spoken at `t`, by binary search over words sorted by start. */
export function wordAt(words: readonly TimedWord[], t: number): TimedWord | null {
  let lo = 0;
  let hi = words.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const w = words[mid];
    if (t < w.start) hi = mid - 1;
    else if (t >= w.end) lo = mid + 1;
    else return w;
  }
  return null;
}

/**
 * Letter-level visemes: a word's letters share its duration evenly, each letter's mouth opens and
 * closes on a sine envelope. Letters map to shapes by their sound (approximate; English).
 */
export function mouthAt(words: readonly TimedWord[], t: number): Mouth {
  const w = wordAt(words, t);
  if (!w) return REST;
  const letters = w.text.toLowerCase().replace(/[^a-z]/g, "");
  if (!letters) return { shape: "ee", open: 0.3 }; // numbers and symbols: generic speech
  const p = (t - w.start) / Math.max(1, w.end - w.start);
  const i = Math.min(letters.length - 1, Math.floor(p * letters.length));
  const local = p * letters.length - i; // 0..1 inside this letter
  const shape = shapeOf(letters[i]);
  const envelope = 0.55 + 0.45 * Math.sin(Math.PI * local);
  return { shape, open: OPENNESS[shape] * envelope };
}

/** Scale the viseme by live loudness (0..1) when an analyser is available. */
export function withAmplitude(mouth: Mouth, amplitude: number | null): Mouth {
  if (amplitude === null || mouth.shape === "rest") return mouth;
  const gain = Math.min(1.3, 0.35 + amplitude * 1.6);
  return { ...mouth, open: Math.min(1, mouth.open * gain) };
}
