import { expect, test } from "vitest";

import { bumperAt, countdown, easeOut, kenBurns, pulse, slideIn, tickerOffset } from "./graphics";

const SPAN = { start: 1000, end: 7000 };

test("lower thirds slide in, hold, and slide out inside their span", () => {
  expect(slideIn(500, SPAN)).toEqual({ x: -1, opacity: 0 });
  const entering = slideIn(1100, SPAN);
  expect(entering.x).toBeGreaterThan(-1);
  expect(entering.x).toBeLessThan(0);
  expect(slideIn(4000, SPAN)).toEqual({ x: 0, opacity: 1 });
  expect(slideIn(6900, SPAN).x).toBeLessThan(0);
  expect(slideIn(7000, SPAN).opacity).toBe(0);
});

test("reduced motion: lower thirds fade instead of sliding", () => {
  const m = slideIn(1100, SPAN, true);
  expect(m.x).toBe(0);
  expect(m.opacity).toBeGreaterThan(0);
  expect(m.opacity).toBeLessThan(1);
});

test("the bumper draws swooshes, then the logo, then the banner, and fades at the end", () => {
  const span = { start: 0, end: 2500 };
  expect(bumperAt(2500, span)).toBeNull();
  const early = bumperAt(200, span);
  expect(early?.swoosh).toBeGreaterThan(0);
  expect(early?.logo).toBe(0);
  expect(early?.banner).toBe(0);
  const mid = bumperAt(1500, span);
  expect(mid).toMatchObject({ swoosh: 1, logo: 1, fade: 1 });
  expect(mid?.banner).toBeGreaterThan(0.9);
  expect(bumperAt(2400, span)?.fade).toBeCloseTo(0.25);
  expect(bumperAt(10, span, true)).toMatchObject({ swoosh: 1, logo: 1, banner: 1 });
});

test("ken burns pushes in and pans across the b-roll", () => {
  const span = { start: 10_000, end: 18_000 };
  expect(kenBurns(9000, span)).toBeNull();
  const a = kenBurns(10_500, span);
  const b = kenBurns(17_000, span);
  expect(b!.scale).toBeGreaterThan(a!.scale);
  expect(b!.x).toBeGreaterThan(a!.x);
  expect(kenBurns(10_000, span)?.opacity).toBe(0);
  expect(kenBurns(14_000, span)?.opacity).toBe(1);
  expect(kenBurns(14_000, span, true)).toMatchObject({ scale: 1.05, x: 0, y: 0 });
});

test("ticker wraps, countdown counts whole seconds, the live dot pulses", () => {
  expect(tickerOffset(0, 1000)).toBeCloseTo(0);
  expect(tickerOffset(2000, 1000, 100)).toBe(-200);
  expect(tickerOffset(12_000, 1000, 100)).toBeCloseTo(-200); // wrapped
  expect(tickerOffset(5000, 0)).toBe(0);
  expect(countdown(25_000, 30_000)).toBe(5);
  expect(countdown(25_001, 30_000)).toBe(5);
  expect(countdown(29_500, 30_000)).toBe(1);
  expect(countdown(31_000, 30_000)).toBe(0);
  expect(pulse(0)).toBe(1);
  expect(pulse(500)).toBeCloseTo(0.1);
  expect(easeOut(2)).toBe(1);
});
