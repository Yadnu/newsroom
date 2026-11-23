// The anchor's body language as a pure function of show time (task 8.4): seeking, pausing and
// replaying give the same pose for the same moment. The SVG only applies these numbers.

import { INTRO_MS, type BroadcastScript } from "./script";

export interface Pose {
  headTilt: number; // degrees, + leans right
  headPitch: number; // degrees, + looks down (papers, nod)
  breath: number; // px the torso rises
  blink: number; // 0 open .. 1 shut
  brow: number; // 0 rest .. 1 raised
  lookDown: number; // 0..1 eyes and head toward the papers
}

export const STILL: Pose = { headTilt: 0, headPitch: 0, breath: 0, blink: 0, brow: 0, lookDown: 0 };

const BLINK_MS = 160;
const NOD_MS = 700;
const BROW_MS = 600;
const SIGN_OFF_MS = 1200; // after the nod, the anchor looks back to the papers

/** Deterministic 0..1 noise for blink spacing. */
function hash01(n: number): number {
  const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
}

/** 0..1..0 over `length` ms starting at `start`. */
function bump(t: number, start: number, length: number): number {
  if (t < start || t >= start + length) return 0;
  return Math.sin((Math.PI * (t - start)) / length);
}

function smooth(x: number): number {
  const c = Math.min(1, Math.max(0, x));
  return c * c * (3 - 2 * c);
}

/** Blinks every 2.8 to 5.2 s at fixed, seeded times. */
export function blinkAt(t: number): number {
  let at = 1800;
  for (let k = 0; at <= t; k++) {
    if (t < at + BLINK_MS) return bump(t, at, BLINK_MS);
    at += 2800 + hash01(k) * 2400;
  }
  return 0;
}

export function poseAt(
  script: Pick<BroadcastScript, "audioOffset" | "nodAt" | "captions">,
  t: number,
  reducedMotion = false,
): Pose {
  // Looks down at the papers through the bumper, up as speech starts, down again after signing off.
  const lookUp = smooth((t - script.audioOffset + 300) / INTRO_MS);
  const backDown = smooth((t - script.nodAt - SIGN_OFF_MS) / 800);
  const lookDown = Math.max(1 - lookUp, backDown);
  if (reducedMotion) return { ...STILL, lookDown: lookDown > 0.5 ? 1 : 0 };

  const nod = bump(t, script.nodAt, NOD_MS);
  let brow = 0;
  for (const c of script.captions) {
    if (t >= c.start && t < c.start + BROW_MS) brow = Math.max(brow, bump(t, c.start, BROW_MS));
  }
  return {
    headTilt: 1.6 * Math.sin((2 * Math.PI * t) / 7000) + 0.7 * Math.sin((2 * Math.PI * t) / 3100),
    headPitch: 9 * lookDown + 7 * nod,
    breath: 1.6 * Math.sin((2 * Math.PI * t) / 4200),
    blink: lookDown > 0.6 ? 0 : blinkAt(t), // eyes on the papers: no visible blink
    brow: 0.8 * brow,
    lookDown,
  };
}
