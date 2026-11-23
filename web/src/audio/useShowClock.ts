"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type MediaLike, ShowClock } from "@/src/broadcast/clock";
import type { BroadcastScript } from "@/src/broadcast/script";

export interface ShowClockState {
  time: number;
  playing: boolean;
  ended: boolean;
  audioFailed: boolean; // captions-only fallback is running
  blocked: boolean; // the browser refused to start audio without a click
}

/** Wraps the <audio> element so a refused or failed play() is reported, never thrown. */
function mediaFor(
  audio: HTMLAudioElement,
  onBlocked: () => void,
  onFailed: () => void,
): MediaLike {
  return {
    get currentTime() {
      return audio.currentTime;
    },
    set currentTime(v: number) {
      audio.currentTime = v;
    },
    get playbackRate() {
      return audio.playbackRate;
    },
    set playbackRate(v: number) {
      audio.playbackRate = v;
    },
    get paused() {
      return audio.paused;
    },
    play() {
      return audio.play().catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "NotAllowedError") onBlocked();
        else if (!(e instanceof DOMException && e.name === "AbortError")) onFailed();
      });
    },
    pause() {
      audio.pause();
    },
  };
}

/**
 * Drives a ShowClock from requestAnimationFrame and exposes its time as React state. The returned
 * controls are stable. `audio` may be null (no audio URL): the show runs captions-only.
 */
export function useShowClock(script: BroadcastScript, audio: HTMLAudioElement | null) {
  const clockRef = useRef<ShowClock | null>(null);
  const [state, setState] = useState<ShowClockState>({
    time: 0,
    playing: false,
    ended: false,
    audioFailed: false,
    blocked: false,
  });

  useEffect(() => {
    const failed = () => {
      clockRef.current?.detachMedia();
      setState((s) => ({ ...s, audioFailed: true }));
    };
    const blocked = () => {
      clockRef.current?.pause();
      setState((s) => ({ ...s, blocked: true, playing: false }));
    };
    const media = audio ? mediaFor(audio, blocked, failed) : null;
    const clock = new ShowClock(script, media);
    clockRef.current = clock;
    audio?.addEventListener("error", failed);
    clock.play();

    let frame = 0;
    const loop = () => {
      const time = clock.tick();
      setState((s) =>
        s.time === time && s.playing === clock.playing && s.ended === clock.ended
          ? s
          : { ...s, time, playing: clock.playing, ended: clock.ended },
      );
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frame);
      audio?.removeEventListener("error", failed);
      clock.pause();
      clockRef.current = null;
    };
  }, [script, audio]);

  const play = useCallback(() => {
    setState((s) => ({ ...s, blocked: false }));
    clockRef.current?.play();
  }, []);
  const pause = useCallback(() => clockRef.current?.pause(), []);
  const toggle = useCallback(() => {
    const c = clockRef.current;
    if (!c) return;
    if (c.playing) c.pause();
    else {
      setState((s) => ({ ...s, blocked: false }));
      c.play();
    }
  }, []);
  const seek = useCallback((ms: number) => clockRef.current?.seek(ms), []);
  const replay = useCallback(() => {
    const c = clockRef.current;
    c?.seek(0);
    c?.play();
  }, []);
  const setRate = useCallback((r: number) => clockRef.current?.setRate(r), []);

  const audioFailed = state.audioFailed || audio === null || !script.audioUrl;
  return { ...state, audioFailed, play, pause, toggle, seek, replay, setRate };
}
