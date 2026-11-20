"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { MIC_RATE, MicChunker } from "@/lib/mic";
import {
  type AnchorEvent,
  type AnswerState,
  AudioClock,
  type CallerQuestionEvent,
  type TimedLine,
  activeLine,
  applyEvent,
  pcm16ToFloat32,
} from "@/lib/player";

export type PlayerLine = { id: string; order: number; text: string; story_title: string | null };

type Status = "idle" | "connecting" | "playing" | "paused" | "done" | "error";

const INTENT_LABEL: Record<CallerQuestionEvent["intent"], string> = {
  follow_up: "follow-up",
  background: "background",
  off_topic: "off topic",
  unknown: "not classified",
};

const SCREEN_LABEL: Record<CallerQuestionEvent["screen_category"], string> = {
  ok: "ok",
  empty: "too short",
  too_long: "too long",
  abusive: "abusive",
  injection: "instructions, not a question",
  off_topic: "off topic",
};

type Answer = { state: AnswerState; lines: { line_id: string; text: string }[] };

const ANSWER_NOTE: Record<AnswerState, string> = {
  thinking: "Checking sources\u2026",
  answering: "",
  unsure: "",
  declined: "Not answered. The briefing continues.",
  failed: "Could not answer just now. The briefing continues.",
};

type Mic = { stream: MediaStream; nodes: AudioNode[]; chunker: MicChunker };

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
  const [talking, setTalking] = useState(false);
  const [heardText, setHeardText] = useState("");
  const [questions, setQuestions] = useState<CallerQuestionEvent[]>([]);
  const [callerError, setCallerError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, Answer>>({});

  const ctxRef = useRef<AudioContext | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const clockRef = useRef<AudioClock | null>(null);
  const timedRef = useRef<TimedLine[]>([]);
  const sourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const statusRef = useRef<Status>("idle");
  const micRef = useRef<Mic | null>(null);
  const talkingRef = useRef(false);
  const workletReady = useRef(false);

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

  const closeMic = useCallback(() => {
    const mic = micRef.current;
    micRef.current = null;
    if (!mic) return;
    for (const n of mic.nodes) n.disconnect();
    for (const t of mic.stream.getTracks()) t.stop();
  }, []);

  const teardown = useCallback(() => {
    closeMic();
    talkingRef.current = false;
    wsRef.current?.close();
    wsRef.current = null;
    stopSources();
    void ctxRef.current?.close();
    ctxRef.current = null;
  }, [stopSources, closeMic]);

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
      } else if (e.type === "caller_interim") {
        setHeardText(e.text);
      } else if (e.type === "caller_question") {
        setHeardText("");
        setQuestions((q) => [e, ...q]);
      } else if (e.type === "answer_status") {
        setAnswers((a) => ({
          ...a,
          [e.question_id]: { state: e.state, lines: e.lines ?? a[e.question_id]?.lines ?? [] },
        }));
        if (e.state === "answering" || e.state === "unsure" || e.state === "declined") {
          setBoth("playing"); // the server resumes after the answer
        }
      } else if (e.type === "caller_error") {
        setHeardText("");
        setCallerError(e.message);
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
    setQuestions([]);
    setAnswers({});
    setHeardText("");
    setCallerError(null);
    workletReady.current = false;
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

  const startTalk = useCallback(async () => {
    const ws = wsRef.current;
    const ctx = ctxRef.current;
    if (talkingRef.current || !ws || ws.readyState !== WebSocket.OPEN || !ctx) return;
    talkingRef.current = true;
    setTalking(true);
    setCallerError(null);
    setHeardText("");
    if (statusRef.current === "playing") pause();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      if (!workletReady.current) {
        await ctx.audioWorklet.addModule("/mic-worklet.js");
        workletReady.current = true;
      }
      if (!talkingRef.current) {
        for (const t of stream.getTracks()) t.stop(); // released before the mic opened
        return;
      }
      const source = ctx.createMediaStreamSource(stream);
      const capture = new AudioWorkletNode(ctx, "mic-capture");
      const mute = ctx.createGain();
      mute.gain.value = 0; // keeps the worklet pulled without playing the mic back
      const chunker = new MicChunker(ctx.sampleRate);
      ws.send(JSON.stringify({ type: "mic_start", sample_rate: MIC_RATE }));
      capture.port.onmessage = (m: MessageEvent<Float32Array>) => {
        for (const chunk of chunker.push(m.data)) ws.send(chunk);
      };
      source.connect(capture).connect(mute).connect(ctx.destination);
      micRef.current = { stream, nodes: [source, capture, mute], chunker };
    } catch {
      talkingRef.current = false;
      setTalking(false);
      setCallerError("Microphone not available. Allow mic access to ask a question.");
    }
  }, [pause]);

  const stopTalk = useCallback(() => {
    if (!talkingRef.current) return;
    talkingRef.current = false;
    setTalking(false);
    const mic = micRef.current;
    const ws = wsRef.current;
    if (mic && ws && ws.readyState === WebSocket.OPEN) {
      const rest = mic.chunker.flush();
      if (rest) ws.send(rest);
      ws.send(JSON.stringify({ type: "mic_end" }));
    }
    closeMic();
  }, [closeMic]);

  const canTalk = status === "playing" || status === "paused";
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
        <button
          type="button"
          className={`talk${talking ? " live" : ""}`}
          disabled={!canTalk && !talking}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            void startTalk();
          }}
          onPointerUp={stopTalk}
          onPointerCancel={stopTalk}
          onKeyDown={(e) => {
            if ((e.key === " " || e.key === "Enter") && !e.repeat) {
              e.preventDefault();
              void startTalk();
            }
          }}
          onKeyUp={(e) => {
            if (e.key === " " || e.key === "Enter") stopTalk();
          }}
          aria-pressed={talking}
        >
          {talking ? "\u25cf Listening\u2026 release to send" : "\ud83c\udf99 Hold to ask"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {(talking || heardText || callerError || questions.length > 0) && (
        <div className="caller" aria-live="polite">
          {heardText && <p className="heard-text">&ldquo;{heardText}&rdquo;</p>}
          {callerError && <p className="error">{callerError}</p>}
          {questions.map((q) => (
            <div key={q.id} className="question">
              {q.allowed ? (
                <span className="badge approved">{INTENT_LABEL[q.intent]}</span>
              ) : (
                <span className="badge rejected" title={q.screen_reason}>
                  not taken: {SCREEN_LABEL[q.screen_category]}
                </span>
              )}
              <b>{q.restated || q.transcript}</b>
              {q.story_title && <span className="muted"> &middot; about {q.story_title}</span>}
              {q.restated && q.restated !== q.transcript && (
                <div className="muted">heard: &ldquo;{q.transcript}&rdquo;</div>
              )}
              {answers[q.id] && ANSWER_NOTE[answers[q.id].state] && (
                <div className="muted">{ANSWER_NOTE[answers[q.id].state]}</div>
              )}
              {answers[q.id]?.lines.map((ln) => (
                <p
                  key={ln.line_id}
                  className={`answer${ln.line_id === active ? " speaking" : ""}`}
                >
                  {ln.text}
                </p>
              ))}
            </div>
          ))}

        </div>
      )}
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
