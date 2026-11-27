import { expect, test } from "vitest";

import { activeCategory, barCategories, categoryHref } from "./categories";

const cats = [
  { name: "AI", stories: 12 },
  { name: "Business", stories: 3 },
];

test("the bar shows only when two or more categories have stories", () => {
  expect(barCategories(cats)).toEqual(cats);
  expect(barCategories([{ name: "AI", stories: 12 }])).toEqual([]);
  expect(barCategories([])).toEqual([]);
  expect(barCategories(undefined)).toEqual([]);
  expect(barCategories([...cats, { name: "Empty", stories: 0 }])).toEqual(cats);
});

test("a known ?category= is kept; unknown, empty or still-loading means All", () => {
  expect(activeCategory("AI", cats)).toBe("AI");
  expect(activeCategory("Sports", cats)).toBeNull();
  expect(activeCategory("", cats)).toBeNull();
  expect(activeCategory(null, cats)).toBeNull();
  // categories still loading: trust the link so a shared URL filters at once
  expect(activeCategory("AI", undefined)).toBe("AI");
});

test("categoryHref keeps other query params and drops category for All", () => {
  expect(categoryHref("AI", "")).toBe("/?category=AI");
  expect(categoryHref(null, "?category=AI")).toBe("/");
  expect(categoryHref("Business", "?x=1&category=AI")).toBe("/?x=1&category=Business");
  expect(categoryHref("Science & Space", "")).toBe("/?category=Science+%26+Space");
});
