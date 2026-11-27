import { expect, test } from "vitest";

import { ApiError, apiUrl, pressCategories, pressPage } from "./client";

test("apiUrl goes through the same-origin rewrite and drops empty params", () => {
  expect(apiUrl("/press/stories", { limit: 10, after_id: undefined })).toBe(
    "/api/press/stories?limit=10",
  );
  expect(apiUrl("/health")).toBe("/api/health");
});

test("pressPage sends the keyset cursor", async () => {
  const seen: string[] = [];
  const fetcher = (async (url: string) => {
    seen.push(url);
    return new Response(JSON.stringify({ stories: [], next: null }), { status: 200 });
  }) as unknown as typeof fetch;
  await pressPage({ latest_at: "2026-11-23T09:00:00Z", id: "abc" }, fetcher);
  expect(seen[0]).toBe(
    "/api/press/stories?limit=10&after_latest_at=2026-11-23T09%3A00%3A00Z&after_id=abc",
  );
});

test("pressPage filters by category only when one is chosen; categories have their own route", async () => {
  const seen: string[] = [];
  const fetcher = (async (url: string) => {
    seen.push(url);
    return new Response(JSON.stringify(url.includes("categories") ? [] : { stories: [], next: null }), {
      status: 200,
    });
  }) as unknown as typeof fetch;
  await pressPage(null, fetcher, "AI");
  await pressPage(null, fetcher, null);
  await pressCategories(fetcher);
  expect(seen).toEqual([
    "/api/press/stories?limit=10&category=AI",
    "/api/press/stories?limit=10",
    "/api/press/categories",
  ]);
});

test("a down backend becomes an ApiError", async () => {
  const down = (async () => {
    throw new TypeError("fetch failed");
  }) as unknown as typeof fetch;
  await expect(pressPage(null, down)).rejects.toMatchObject({ status: 0 });
  const bad = (async () => new Response("", { status: 502 })) as unknown as typeof fetch;
  await expect(pressPage(null, bad)).rejects.toBeInstanceOf(ApiError);
});

test("describeError gives readers a sentence, not a status code", async () => {
  const { describeError } = await import("./client");
  expect(describeError(new ApiError(0, "/x"))).toMatch(/offline/);
  expect(describeError(new ApiError(404, "/x"))).toMatch(/no longer in the feed/);
  expect(describeError(new ApiError(502, "/x"))).toMatch(/server had a problem/);
  expect(describeError(new ApiError(418, "/x"))).toBe("The request failed (418).");
  expect(describeError(new Error("boom"))).toMatch(/Something went wrong/);
});
