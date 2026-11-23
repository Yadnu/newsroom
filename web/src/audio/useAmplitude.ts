"use client";

import { useEffect, useRef } from "react";

interface Tap {
  ctx: AudioContext;
  analyser: AnalyserNode;
  buffer: Uint8Array<ArrayBuffer>;
}

// createMediaElementSource may be called once per element.
const taps = new WeakMap<HTMLMediaElement, Tap>();

/**
 * Live loudness (0..1) of the telecast audio for lip sync, used only when the TTS gave no word
 * timings. It taps the element through Web Audio once the context is running (after a user
 * gesture), so a suspended context can never silence the broadcast. Returns a getter for the
 * render loop; null until tapped or when `enabled` is false.
 */
export function useAmplitude(
  audio: HTMLAudioElement | null,
  enabled: boolean,
  playing: boolean,
): () => number | null {
  const tap = useRef<Tap | null>(null);

  useEffect(() => {
    if (!audio || !enabled || !playing || typeof AudioContext === "undefined") return;
    const existing = taps.get(audio);
    if (existing) {
      tap.current = existing;
      return;
    }
    let cancelled = false;
    const ctx = new AudioContext();
    void ctx
      .resume()
      .then(() => {
        if (cancelled || ctx.state !== "running" || taps.has(audio)) return;
        const source = ctx.createMediaElementSource(audio);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
        analyser.connect(ctx.destination);
        const t: Tap = { ctx, analyser, buffer: new Uint8Array(new ArrayBuffer(analyser.fftSize)) };
        taps.set(audio, t);
        tap.current = t;
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [audio, enabled, playing]);

  return () => {
    const t = tap.current;
    if (!t || !enabled) return null;
    t.analyser.getByteTimeDomainData(t.buffer);
    let sum = 0;
    for (const v of t.buffer) {
      const x = (v - 128) / 128;
      sum += x * x;
    }
    return Math.min(1, Math.sqrt(sum / t.buffer.length) * 4);
  };
}
