// Pure paging rules for the full-screen feed: one card per step, from wheel, keys or touch.

export const WHEEL_THRESHOLD = 60; // accumulated deltaY (px) that counts as one step
export const SWIPE_THRESHOLD = 50; // finger travel (px) that counts as one step
export const STEP_COOLDOWN_MS = 450; // ignore input while a card transition runs
export const PREFETCH_WITHIN = 3; // load the next page when this close to the end

export type Step = -1 | 0 | 1;

export function clampIndex(index: number, count: number): number {
  if (count <= 0) return 0;
  return Math.min(Math.max(index, 0), count - 1);
}

/** Wheel deltas accumulate until they pass the threshold; returns the step and the remainder. */
export function wheelStep(accumulated: number, deltaY: number): { step: Step; rest: number } {
  const total = accumulated + deltaY;
  if (total >= WHEEL_THRESHOLD) return { step: 1, rest: 0 };
  if (total <= -WHEEL_THRESHOLD) return { step: -1, rest: 0 };
  return { step: 0, rest: total };
}

/** Swiping up (finger moves up, negative dy) goes to the next story. */
export function swipeStep(startY: number, endY: number): Step {
  const dy = endY - startY;
  if (dy <= -SWIPE_THRESHOLD) return 1;
  if (dy >= SWIPE_THRESHOLD) return -1;
  return 0;
}

const KEY_STEPS: Record<string, Step> = {
  ArrowDown: 1,
  PageDown: 1,
  j: 1,
  " ": 1,
  ArrowUp: -1,
  PageUp: -1,
  k: -1,
};

export function keyStep(key: string, shiftKey = false): Step {
  if (key === " " && shiftKey) return -1;
  return KEY_STEPS[key] ?? 0;
}

export function shouldPrefetch(index: number, count: number, hasMore: boolean): boolean {
  return hasMore && count - 1 - index < PREFETCH_WITHIN;
}
