import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { BroadcastScript } from "@/src/broadcast/script";

import { useShowClock } from "./useShowClock";

const SCRIPT = {
  duration: 10_000,
  audioOffset: 0, // speech from the start so play() is called at once
  audioDuration: 8000,
  audioUrl: "/media/telecasts/x.wav",
} as BroadcastScript;

function audioElement(play: () => Promise<void>): HTMLAudioElement {
  const el = document.createElement("audio");
  Object.defineProperty(el, "paused", { configurable: true, get: () => true });
  el.play = play;
  el.pause = () => undefined;
  return el;
}

afterEach(() => vi.restoreAllMocks());

describe("useShowClock fallbacks", () => {
  test("an audio error switches the show to captions only", async () => {
    const el = audioElement(() => Promise.resolve());
    const { result } = renderHook(() => useShowClock(SCRIPT, el));
    expect(result.current.audioFailed).toBe(false);
    await act(async () => {
      el.dispatchEvent(new Event("error"));
    });
    expect(result.current.audioFailed).toBe(true);
  });

  test("a play() the browser refuses (no gesture) shows the play button", async () => {
    const el = audioElement(() => Promise.reject(new DOMException("no gesture", "NotAllowedError")));
    const { result } = renderHook(() => useShowClock(SCRIPT, el));
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.blocked).toBe(true);
    expect(result.current.audioFailed).toBe(false);
    act(() => result.current.play());
    expect(result.current.blocked).toBe(false);
  });

  test("no audio element: captions only from the start", () => {
    const { result } = renderHook(() => useShowClock(SCRIPT, null));
    expect(result.current.audioFailed).toBe(true);
  });
});
