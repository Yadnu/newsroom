// On-screen graphics as pure functions of show time (task 8.5): bumper, lower thirds, B-roll, ticker,
// outro countdown. Components only apply the numbers, so pause, seek and replay hold every frame.

import type { Span } from "./script";

export interface Motion {
  x: number; // 0 = in place, -1 = fully off to the left (fraction of own width)
  opacity: number;
}

const HIDDEN: Motion = { x: -1, opacity: 0 };

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x));
}

/** Ease-out cubic. */
export function easeOut(x: number): number {
  const c = clamp01(x);
  return 1 - (1 - c) ** 3;
}

/** A bar that slides in from the left at `span.start` and out before `span.end`. Reduced motion: fades. */
export function slideIn(t: number, span: Span, reduced = false, inMs = 450, outMs = 350): Motion {
  if (t < span.start || t >= span.end) return HIDDEN;
  const enter = easeOut((t - span.start) / inMs);
  const leave = easeOut((span.end - t) / outMs);
  const k = Math.min(enter, leave);
  return reduced ? { x: 0, opacity: k } : { x: k - 1, opacity: Math.min(1, k * 1.4) };
}

export interface Bumper {
  swoosh: number; // 0..1 how far the swoosh lines have drawn
  logo: number; // 0..1 logo scale-in
  banner: number; // 0..1 banner wipe
  fade: number; // 1 visible .. 0 gone (fades out over the last 400 ms)
}

/** The intro bumper over `span` (0..BUMPER_MS): swooshes, then the logo, then the banner. */
export function bumperAt(t: number, span: Span, reduced = false): Bumper | null {
  if (t < span.start || t >= span.end) return null;
  const u = t - span.start;
  const fade = clamp01((span.end - t) / 400);
  if (reduced) return { swoosh: 1, logo: 1, banner: 1, fade };
  return {
    swoosh: easeOut(u / 900),
    logo: easeOut((u - 300) / 600),
    banner: easeOut((u - 900) / 450),
    fade,
  };
}

export interface KenBurns {
  scale: number;
  x: number; // % of the frame
  y: number;
  opacity: number;
}

/** B-roll: a slow push-in and pan across the span, fading in and out. */
export function kenBurns(t: number, span: Span, reduced = false): KenBurns | null {
  if (t < span.start || t >= span.end) return null;
  const length = Math.max(1, span.end - span.start);
  const p = (t - span.start) / length;
  const opacity = Math.min(clamp01((t - span.start) / 400), clamp01((span.end - t) / 400));
  if (reduced) return { scale: 1.05, x: 0, y: 0, opacity };
  return { scale: 1.06 + 0.12 * p, x: -3 + 6 * p, y: 1.5 - 3 * p, opacity };
}

/** Ticker offset in px: scrolls `pxPerSec` to the left, wrapping every `width` px. */
export function tickerOffset(t: number, width: number, pxPerSec = 90): number {
  if (width <= 0) return 0;
  return -((t / 1000) * pxPerSec) % width;
}

/** Whole seconds left before auto-advance (shown in the outro). */
export function countdown(t: number, duration: number): number {
  return Math.max(0, Math.ceil((duration - t) / 1000));
}

/** The LIVE dot pulses once per second. */
export function pulse(t: number): number {
  return 0.55 + 0.45 * Math.cos((2 * Math.PI * t) / 1000);
}
