"use client";

import { RATES, type Rate, usePlayer } from "@/src/store/player";

function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export interface ControlsProps {
  time: number;
  duration: number;
  playing: boolean;
  audioFailed: boolean;
  onToggle: () => void;
  onReplay: () => void;
  onSeek: (ms: number) => void;
  onRate: (rate: Rate) => void;
  onPrev?: () => void;
  onNext?: () => void;
  onExit: () => void;
}

const BTN =
  "rounded px-2.5 py-1.5 font-body text-sm text-white/85 hover:bg-white/10 hover:text-white disabled:opacity-30";

export function Controls(p: ControlsProps) {
  const { captions, muted, rate, toggleCaptions, toggleMuted, setRate } = usePlayer();
  return (
    <div className="flex flex-col gap-1 bg-black/70 px-3 py-2 text-white">
      <input
        type="range"
        aria-label="Seek"
        min={0}
        max={p.duration}
        step={100}
        value={Math.round(p.time)}
        onChange={(e) => p.onSeek(Number(e.target.value))}
        className="h-1 w-full cursor-pointer accent-[var(--color-breaking)]"
      />
      <div className="flex flex-wrap items-center gap-1">
        <button type="button" className={BTN} onClick={p.onPrev} disabled={!p.onPrev} aria-label="Previous story">
          ⏮
        </button>
        <button type="button" className={BTN} onClick={p.onToggle} aria-label={p.playing ? "Pause" : "Play"}>
          {p.playing ? "❚❚" : "▶"}
        </button>
        <button type="button" className={BTN} onClick={p.onNext} disabled={!p.onNext} aria-label="Next story">
          ⏭
        </button>
        <button type="button" className={BTN} onClick={p.onReplay} aria-label="Replay">
          ↺
        </button>
        <span className="px-2 font-body text-xs tabular-nums text-white/70">
          {clock(p.time)} / {clock(p.duration)}
        </span>
        {p.audioFailed && (
          <span className="rounded bg-white/10 px-2 py-0.5 font-body text-xs text-white/70">
            Captions only: audio unavailable
          </span>
        )}
        <span className="ml-auto" />
        <button
          type="button"
          className={BTN}
          onClick={toggleMuted}
          aria-pressed={muted}
          aria-label={muted ? "Unmute" : "Mute"}
        >
          {muted ? "🔇" : "🔊"}
        </button>
        <button
          type="button"
          className={BTN}
          onClick={toggleCaptions}
          aria-pressed={captions}
          aria-label="Captions"
        >
          CC
        </button>
        <label className="flex items-center gap-1 font-body text-xs text-white/70">
          <span className="sr-only">Speed</span>
          <select
            value={rate}
            onChange={(e) => {
              const r = Number(e.target.value) as Rate;
              setRate(r);
              p.onRate(r);
            }}
            className="rounded bg-white/10 px-1 py-1 text-white"
          >
            {RATES.map((r) => (
              <option key={r} value={r} className="text-set">
                {r}×
              </option>
            ))}
          </select>
        </label>
        <button type="button" className={BTN} onClick={p.onExit} aria-label="Exit to the feed">
          ✕
        </button>
      </div>
    </div>
  );
}
