import { describe, expect, test } from "vitest";

import type { TelecastView } from "@/src/api/client";

import {
  BUMPER_MS,
  OUTRO_MS,
  activeCaption,
  buildBroadcastScript,
  isBreaking,
  segmentsAt,
} from "./script";

const NOW = new Date("2026-11-23T12:00:00Z");

function telecast(over: Partial<TelecastView> = {}, imageUrl: string | null = "https://i.test/a.jpg"): TelecastView {
  return {
    id: "t1",
    story_id: "s1",
    briefing_id: "b1",
    step: "ready",
    error: null,
    created_at: "2026-11-23T11:00:00Z",
    updated_at: "2026-11-23T11:01:00Z",
    audio_url: "/media/telecasts/t1.wav",
    duration_ms: 20_000,
    lines: [
      { id: "l2", text: "Second.", start_ms: 6000, end_ms: 12_000, words: [] },
      {
        id: "l1",
        text: "First one.",
        start_ms: 0,
        end_ms: 5700,
        words: [
          { text: "First", start_ms: 100, end_ms: 2500 },
          { text: "one.", start_ms: 2500, end_ms: 5700 },
        ],
      },
      { id: "l3", text: "Third.", start_ms: 12_300, end_ms: 20_000, words: [] },
    ],
    verdicts: { approved: 4, rejected: 1 },
    story: {
      id: "s1",
      title: "Chip launch",
      summary: null,
      image_url: imageUrl,
      image_outlet: imageUrl ? "Ledger Tech" : null,
      outlets: ["A", "B"],
      n_sources: 2,
      latest_at: "2026-11-23T08:00:00Z",
      sources: [],
      telecast: null,
    },
    ...over,
  };
}

describe("buildBroadcastScript", () => {
  test("lays the speech after the bumper and the outro after the speech", () => {
    const s = buildBroadcastScript(telecast(), NOW);
    expect(s.audioOffset).toBe(BUMPER_MS);
    expect(s.audioDuration).toBe(20_000);
    expect(s.duration).toBe(BUMPER_MS + 20_000 + OUTRO_MS);
    const kinds = s.segments.map((x) => [x.kind, x.start, x.end]);
    expect(kinds).toContainEqual(["bumper", 0, BUMPER_MS]);
    expect(kinds).toContainEqual(["body", BUMPER_MS, BUMPER_MS + 20_000]);
    expect(kinds).toContainEqual(["outro", BUMPER_MS + 20_000, s.duration]);
    expect(s.nodAt).toBe(BUMPER_MS + 20_000);
    expect(s.banner).toBe("TOP STORY");
    expect([s.approved, s.claims]).toEqual([4, 5]);
  });

  test("captions follow line order on show time", () => {
    const s = buildBroadcastScript(telecast(), NOW);
    expect(s.captions.map((c) => [c.lineId, c.start, c.end])).toEqual([
      ["l1", BUMPER_MS, BUMPER_MS + 5700],
      ["l2", BUMPER_MS + 6000, BUMPER_MS + 12_000],
      ["l3", BUMPER_MS + 12_300, BUMPER_MS + 20_000],
    ]);
    expect(activeCaption(s, BUMPER_MS + 100)?.lineId).toBe("l1");
    expect(activeCaption(s, BUMPER_MS + 5800)).toBeNull(); // the gap between lines
    expect(activeCaption(s, BUMPER_MS + 19_999)?.lineId).toBe("l3");
    expect(activeCaption(s, 100)).toBeNull(); // bumper
  });

  test("b-roll starts on a caption boundary inside the body", () => {
    const s = buildBroadcastScript(telecast(), NOW);
    const broll = s.segments.find((x) => x.kind === "broll");
    expect(broll).toEqual({ kind: "broll", start: BUMPER_MS + 6000, end: BUMPER_MS + 11_000 });
    expect(segmentsAt(s, BUMPER_MS + 7000)).toEqual(["body", "broll"]);
  });

  test("no image or a short story: no b-roll", () => {
    expect(buildBroadcastScript(telecast({}, null), NOW).segments.some((x) => x.kind === "broll")).toBe(false);
    const short = telecast({ duration_ms: 9000, lines: [{ id: "l", text: "x", start_ms: 0, end_ms: 9000, words: [] }] });
    expect(buildBroadcastScript(short, NOW).segments.some((x) => x.kind === "broll")).toBe(false);
  });

  test("lower thirds stay inside the body", () => {
    const s = buildBroadcastScript(telecast(), NOW);
    for (const l of s.lowerThirds) {
      expect(l.start).toBeGreaterThanOrEqual(BUMPER_MS);
      expect(l.end).toBeLessThanOrEqual(BUMPER_MS + 20_000);
    }
    expect(s.lowerThirds.map((l) => l.kind)).toEqual(["headline", "factcheck"]);
  });

  test("captions carry TTS words on show time, or estimates", () => {
    const s = buildBroadcastScript(telecast(), NOW);
    const [first, second] = s.captions;
    expect(first.estimated).toBe(false);
    expect(first.words).toEqual([
      { text: "First", start: BUMPER_MS + 100, end: BUMPER_MS + 2500 },
      { text: "one.", start: BUMPER_MS + 2500, end: BUMPER_MS + 5700 },
    ]);
    expect(second.estimated).toBe(true);
    expect(second.words).toEqual([{ text: "Second.", start: BUMPER_MS + 6000, end: BUMPER_MS + 12_000 }]);
    expect(s.wordsEstimated).toBe(true);
    expect(s.words.map((w) => w.text)).toEqual(["First", "one.", "Second.", "Third."]);
  });

  test("lower thirds never overlap, even on a short story", () => {
    for (const dur of [6000, 9000, 20_000, 60_000]) {
      const lines = [{ id: "l", text: "x", start_ms: 0, end_ms: dur, words: [] }];
      const s = buildBroadcastScript(telecast({ duration_ms: dur, lines }), NOW);
      const [a, b] = s.lowerThirds;
      if (b) expect(b.start).toBeGreaterThanOrEqual(a.end);
      for (const l of s.lowerThirds) expect(l.end - l.start).toBeGreaterThanOrEqual(1500);
    }
    const short = buildBroadcastScript(
      telecast({ duration_ms: 4000, lines: [{ id: "l", text: "x", start_ms: 0, end_ms: 4000, words: [] }] }),
      NOW,
    );
    expect(short.lowerThirds.map((l) => l.kind)).toEqual(["headline"]);
  });

  test("a telecast without lines still has a timeline", () => {
    const s = buildBroadcastScript(telecast({ lines: [], duration_ms: null, story: null }), NOW);
    expect(s.audioDuration).toBe(0);
    expect(s.captions).toEqual([]);
    expect(s.duration).toBe(BUMPER_MS + OUTRO_MS);
    expect(s.title).toBe("");
  });
});

test("isBreaking: fresh and widely covered", () => {
  expect(isBreaking("2026-11-23T10:30:00Z", 3, NOW)).toBe(true);
  expect(isBreaking("2026-11-23T10:30:00Z", 2, NOW)).toBe(false);
  expect(isBreaking("2026-11-23T07:00:00Z", 5, NOW)).toBe(false);
  expect(isBreaking("2026-11-23T13:00:00Z", 5, NOW)).toBe(false); // future timestamp
});
