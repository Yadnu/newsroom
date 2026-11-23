import { expect, test } from "vitest";

import { gradientFor, outletsLine, timeAgo } from "./look";

test("gradientFor is stable per story and differs between stories", () => {
  const a = gradientFor("0cd76aa4-9264-4324-939a-56dcfb8b01b8");
  expect(a).toBe(gradientFor("0cd76aa4-9264-4324-939a-56dcfb8b01b8"));
  expect(a).toMatch(/^linear-gradient\(\d+deg, #[0-9a-f]{6} 0%, #[0-9a-f]{6} 100%\)$/);
  const others = new Set(["a", "b", "c", "d", "e", "f", "g"].map(gradientFor));
  expect(others.size).toBeGreaterThan(1);
});

test("timeAgo", () => {
  const now = new Date("2026-11-23T12:00:00Z");
  expect(timeAgo("2026-11-23T11:59:30Z", now)).toBe("just now");
  expect(timeAgo("2026-11-23T11:48:00Z", now)).toBe("12 min ago");
  expect(timeAgo("2026-11-23T09:00:00Z", now)).toBe("3 h ago");
  expect(timeAgo("2026-11-22T11:00:00Z", now)).toBe("1 day ago");
  expect(timeAgo("2026-11-20T11:00:00Z", now)).toBe("3 days ago");
  expect(timeAgo("2026-11-01T11:00:00Z", now)).toBe("1 Nov");
  expect(timeAgo("not a date", now)).toBe("");
});

test("outletsLine", () => {
  expect(outletsLine(["A", "B"])).toBe("A · B");
  expect(outletsLine(["A", "B", "C", "D", "E"])).toBe("A · B · C +2");
});
