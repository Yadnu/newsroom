import assert from "node:assert/strict";
import { test } from "vitest";

import { ms, safeHref, usd, verdictCounts, when } from "./format.ts";

test("safeHref only allows http(s) links from feed data", () => {
  assert.equal(safeHref("https://wired.test/a?b=1"), "https://wired.test/a?b=1");
  assert.equal(safeHref("http://x.test"), "http://x.test/");
  assert.equal(safeHref("javascript:alert(1)"), undefined);
  assert.equal(safeHref("data:text/html,hi"), undefined);
  assert.equal(safeHref("not a url"), undefined);
});

test("durations and money", () => {
  assert.equal(ms(null), "–");
  assert.equal(ms(420.4), "420 ms");
  assert.equal(ms(9_000), "9.0 s");
  assert.equal(ms(125_000), "2m 5s");
  assert.equal(usd(0), "$0");
  assert.equal(usd(0.0021), "$0.0021");
  assert.equal(usd(1.234), "$1.23");
});

test("verdict counts keep a fixed order and drop zeros", () => {
  assert.deepEqual(verdictCounts({ pending: 2, approved: 5, rejected: 0, odd: 1 }), [
    ["approved", 5],
    ["pending", 2],
    ["odd", 1],
  ]);
});

test("when renders UTC", () => {
  assert.equal(when("2026-11-19T09:05:00Z"), "19 Nov 2026, 09:05 UTC");
  assert.equal(when(null), "–");
});
