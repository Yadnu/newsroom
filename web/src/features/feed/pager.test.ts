import { describe, expect, test } from "vitest";

import {
  clampIndex,
  keyStep,
  shouldPrefetch,
  swipeStep,
  WHEEL_THRESHOLD,
  wheelStep,
} from "./pager";

describe("pager", () => {
  test("clampIndex keeps the index inside the feed", () => {
    expect(clampIndex(-1, 5)).toBe(0);
    expect(clampIndex(7, 5)).toBe(4);
    expect(clampIndex(2, 5)).toBe(2);
    expect(clampIndex(3, 0)).toBe(0);
  });

  test("wheel deltas accumulate into one step", () => {
    expect(wheelStep(0, 20)).toEqual({ step: 0, rest: 20 });
    expect(wheelStep(20, WHEEL_THRESHOLD)).toEqual({ step: 1, rest: 0 });
    expect(wheelStep(-30, -40)).toEqual({ step: -1, rest: 0 });
  });

  test("swiping up goes to the next story", () => {
    expect(swipeStep(500, 380)).toBe(1);
    expect(swipeStep(300, 420)).toBe(-1);
    expect(swipeStep(300, 320)).toBe(0);
  });

  test("keys", () => {
    expect(keyStep("ArrowDown")).toBe(1);
    expect(keyStep("PageUp")).toBe(-1);
    expect(keyStep(" ")).toBe(1);
    expect(keyStep(" ", true)).toBe(-1);
    expect(keyStep("Enter")).toBe(0);
  });

  test("prefetch near the end only while more pages exist", () => {
    expect(shouldPrefetch(7, 10, true)).toBe(true);
    expect(shouldPrefetch(2, 10, true)).toBe(false);
    expect(shouldPrefetch(9, 10, false)).toBe(false);
  });
});
