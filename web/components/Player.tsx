"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  type AnchorEvent,
  AudioClock,
  type TimedLine,
  activeLine,
  applyEvent,
  pcm16ToFloat32,
} from "@/lib/player";

export type PlayerLine = { id: string; order: number; text: string; story_title: string | null };

type Status = "idle" | "connecting" | "playing" | "paused" | "done" | "error";

const CLOSE_REASONS: Record<number, string> = {
  4404: "This briefing does not exist.",
  4409: "Nothing in this briefing was cleared for air.",
  4500: "Text-to-speech is not configured on the server.",
};

export function Player({
  briefingId,
  wsUrl,
  lines,
  selected,
}: {
  briefingId: string;
  wsUrl: string;
  lines: PlayerLine[];
  selected?: string;
}) {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [heard, setHeard] = useState<Set<string>>(new Set());
  const [elapsed, setElapsed] = useState(0);

  const ctxRef = useRef<AudioContext | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const clockRef = useRef<AudioClock | null>(null);
  const timedRef = useRef<TimedLine[]>([]);
  const sourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const statusRef = useRef<Status>("idle");

  const setBoth = useCallback((s: Status) => {
    statusRef.current = s;
    setStatus(s);
  }, []);

  const stopSources = useCallback(() => {
    for (const src of sourcesRef.current) {
      try {
        src.stop();
      } catch {
        // already ended
      }
    }
    sourcesRef.current.clear();
  }, []);

  const teardown = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    stopSources();
    void ctxRef.current?.close();
    ctxRef.current = null;
  }, [stopSources]);

  useEffect(() => teardown, [teardown]);

  const running = status === "playing" || status === "paused" || status === "done";
  useEffect(() => {
    if (!running) return;
    let raf = 0;
    const step = () => {
      const ctx = ctxRef.current;
      const clock = clockRef.current;
      if (ctx && clock) {
        const ms = clock.clockAt(ctx.currentTime);
        const now = activeLine(timedRef.current, ms);
        setActive(now);
        if (ms != null) setElapsed(ms);
        if (now) setHeard((h) => (h.has(now) ? h : new Set(h).add(now)));
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [running]);

  const onEvent = useCallback(
    (e: AnchorEvent) => {
      if (e.type === "start") {
        clockRef.current = new AudioClock(e.sample_rate);
        setBoth("playing");
      } else if (e.type === "line" || e.type === "line_end") {
        timedRef.current = applyEvent(timedRef.current, e);
      } else if (e.type === "done") {
        setBoth("done");
      }
    },
    [setBoth],
  );

  const onAudio = useCallback((data: ArrayBuffer) => {
    const ctx = ctxRef.current;
    const clock = clockRef.current;
    if (!ctx || !clock || statusRef.current === "paused") return;
    const samples = pcm16ToFloat32(data);
    if (!samples.length) return;
    const buffer = ctx.createBuffer(1, samples.length, clock.sampleRate);
    buffer.copyToChannel(samples, 0);
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    src.onended = () => sourcesRef.current.delete(src);
    src.start(clock.schedule(samples.length, ctx.currentTime));
    sourcesRef.current.add(src);
  }, []);

  const play = useCallback(() => {
    teardown();
    setError(null);
    setHeard(new Set());
    setActive(null);
    setElapsed(0);
    timedRef.current = [];
    clockRef.current = null;
    setBoth("connecting");
    const ctx = new AudioContext(); // created on the click, so the browser allows sound
    ctxRef.current = ctx;
    const ws = new WebSocket(`${wsUrl}/anchor/briefings/${encodeURIComponent(briefingId)}/live`);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    ws.onmessage = (m) => {
      if (typeof m.data === "string") onEvent(JSON.parse(m.data) as AnchorEvent);
      else onAudio(m.data as ArrayBuffer);
    };
    ws.onclose = (c) => {
      if (CLOSE_REASONS[c.code]) {
        setError(CLOSE_REASONS[c.code]);
        setBoth("error");
      } else if (statusRef.current === "connecting") {
        setError("Could not reach the Anchor. Is the API running?");
        setBoth("error");
      }
    };
  }, [briefingId, wsUrl, onAudio, onEvent, setBoth, teardown]);

  const pause = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: "pause" }));
    stopSources(); // silence now, without waiting for the server
    clockRef.current?.reset();
    setBoth("paused");
  }, [setBoth, stopSources]);

  const resume = useCallback(() => {
    void ctxRef.current?.resume();
    wsRef.current?.send(JSON.stringify({ type: "resume" }));
    setBoth("playing");
  }, [setBoth]);

  const finished = status === "done" && active == null;
  return (
    <section className="card player" aria-label="Briefing player">
      <div className="controls">
        {status === "idle" || status === "error" || finished ? (
          <button type="button" onClick={play}>
            ▶ {status === "idle" ? "Play briefing" : "Play again"}
          </button>
        ) : status === "paused" ? (
          <button type="button" onClick={resume}>
            ▶ Resume
          </button>
        ) : (
          <button type="button" onClick={pause} disabled={status === "connecting"}>
            ❚❚ Pause
          </button>
        )}
        <span className="muted mono">
          {status === "connecting" ? "connecting…" : `${(elapsed / 1000).toFixed(1)} s`}
        </span>
        {status === "paused" && <span className="muted">Paused. Resume replays the sentence.</span>}
        {finished && <span className="muted">End of briefing.</span>}
      </div>
      {error && <p className="error">{error}</p>}
      <ol className="script transcript">
        {lines.map((ln, i) => {
          const held = (finished || status === "done") && !heard.has(ln.id) && active !== ln.id;
          return (
            <li key={ln.id}>
              {ln.story_title && ln.story_title !== lines[i - 1]?.story_title && (
                <div className="story">{ln.story_title}</div>
              )}
              <Link
                href={`/briefings/${briefingId}/listen?line=${ln.id}`}
                scroll={false}
                aria-current={ln.id === selected ? "true" : undefined}
                className={[
                  ln.id === active ? "speaking" : "",
                  heard.has(ln.id) ? "heard" : "",
                  held ? "held" : "",
                ].join(" ")}
                title={held ? "Held back by the Standards Desk" : "Show claims and sources"}
              >
                {ln.text}
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
