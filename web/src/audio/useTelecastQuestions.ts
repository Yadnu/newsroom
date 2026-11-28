"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { MIC_RATE, MicChunker } from "@/lib/mic";
import { type AskAction, IDLE, type QuestionEvent, askReducer, isBusy, questionsUrl } from "@/src/broadcast/questions";

type Mic = { stream: MediaStream; nodes: AudioNode[]; chunker: MicChunker };
type Outgoing = string | ArrayBuffer;

const CLOSE_NOTES: Record<number, string> = {
  4404: "This broadcast is no longer available for questions.",
  4409: "This broadcast is not ready for questions yet.",
};

/**
 * Questions during a telecast (task 9.6). The socket opens on the first question and stays open for
 * the rest of the show. `startTalk`/`stopTalk` stream the mic while held (push-to-talk); `ask` sends
 * typed text. When an answer arrives its audio plays here; `answerTime` follows it for captions.
 */
export function useTelecastQuestions(telecastId: string, wsBase: string, muted: boolean) {
  const [state, dispatch] = useReducer(askReducer, IDLE);
  const [played, setPlayed] = useState<{ url: string; ms: number } | null>(null);
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);
  const wsRef = useRef<WebSocket | null>(null);
  const outbox = useRef<Outgoing[]>([]);
  const ctxRef = useRef<AudioContext | null>(null);
  const workletReady = useRef(false);
  const micRef = useRef<Mic | null>(null);
  const talking = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const socket = useCallback((): WebSocket => {
    const current = wsRef.current;
    if (current && current.readyState <= WebSocket.OPEN) return current; // connecting or open
    const ws = new WebSocket(questionsUrl(wsBase, telecastId));
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      for (const m of outbox.current.splice(0)) ws.send(m);
    };
    ws.onmessage = (m) => {
      if (typeof m.data === "string") dispatch(JSON.parse(m.data) as QuestionEvent);
    };
    ws.onclose = (c) => {
      if (wsRef.current !== ws) return;
      wsRef.current = null;
      outbox.current = [];
      const note = CLOSE_NOTES[c.code];
      dispatch(note ? { type: "caller_error", message: note } : { type: "closed" });
    };
    wsRef.current = ws;
    return ws;
  }, [telecastId, wsBase]);

  const send = useCallback(
    (m: Outgoing) => {
      const ws = socket();
      if (ws.readyState === WebSocket.OPEN) ws.send(m);
      else outbox.current.push(m);
    },
    [socket],
  );

  const ask = useCallback(
    (text: string) => {
      const q = text.trim();
      if (!q || isBusy(stateRef.current)) return;
      dispatch({ type: "sent", text: q });
      send(JSON.stringify({ type: "ask", text: q }));
    },
    [send],
  );

  const closeMic = useCallback(() => {
    const mic = micRef.current;
    micRef.current = null;
    if (!mic) return;
    for (const n of mic.nodes) n.disconnect();
    for (const t of mic.stream.getTracks()) t.stop();
  }, []);

  const startTalk = useCallback(async () => {
    if (talking.current || isBusy(stateRef.current)) return;
    talking.current = true;
    dispatch({ type: "listening" });
    try {
      const ctx = ctxRef.current ?? new AudioContext(); // made on the press: a user gesture
      ctxRef.current = ctx;
      await ctx.resume();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      if (!workletReady.current) {
        await ctx.audioWorklet.addModule("/mic-worklet.js");
        workletReady.current = true;
      }
      if (!talking.current) {
        for (const t of stream.getTracks()) t.stop(); // released before the mic opened
        dispatch({ type: "caller_error", message: "Hold the button while you ask." });
        return;
      }
      const source = ctx.createMediaStreamSource(stream);
      const capture = new AudioWorkletNode(ctx, "mic-capture");
      const mute = ctx.createGain();
      mute.gain.value = 0; // keeps the worklet pulled without playing the mic back
      const chunker = new MicChunker(ctx.sampleRate);
      send(JSON.stringify({ type: "mic_start", sample_rate: MIC_RATE }));
      capture.port.onmessage = (m: MessageEvent<Float32Array>) => {
        for (const chunk of chunker.push(m.data)) send(chunk);
      };
      source.connect(capture).connect(mute).connect(ctx.destination);
      micRef.current = { stream, nodes: [source, capture, mute], chunker };
    } catch {
      talking.current = false;
      closeMic();
      dispatch({ type: "caller_error", message: "Microphone not available. Allow mic access, or type your question." });
    }
  }, [send, closeMic]);

  const stopTalk = useCallback(() => {
    if (!talking.current) return;
    talking.current = false;
    const mic = micRef.current;
    if (mic) {
      const rest = mic.chunker.flush();
      if (rest) send(rest);
      send(JSON.stringify({ type: "mic_end" }));
    }
    closeMic();
  }, [send, closeMic]);

  const finish = useCallback((a: AskAction = { type: "answer_done" }) => {
    audioRef.current?.pause();
    dispatch(a);
  }, []);

  // Play the answer: its audio when it was voiced, else hold the captions long enough to read.
  const answer = state.status === "answering" ? state.answer : null;
  useEffect(() => {
    if (!answer) return;
    if (!answer.audioUrl) {
      const t = setTimeout(() => dispatch({ type: "answer_done" }), answer.durationMs);
      return () => clearTimeout(t);
    }
    const audio = new Audio(answer.audioUrl);
    audioRef.current = audio;
    audio.muted = muted;
    const url = answer.audioUrl;
    const tick = () => setPlayed({ url, ms: audio.currentTime * 1000 });
    const done = () => dispatch({ type: "answer_done" });
    audio.addEventListener("timeupdate", tick);
    audio.addEventListener("ended", done);
    audio.addEventListener("error", done);
    void audio.play().catch(done); // refused or failed: the captions were shown, move on
    return () => {
      audio.pause();
      audio.removeEventListener("timeupdate", tick);
      audio.removeEventListener("ended", done);
      audio.removeEventListener("error", done);
      if (audioRef.current === audio) audioRef.current = null;
    };
    // `muted` is applied below without restarting the answer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answer]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.muted = muted;
  }, [muted]);

  useEffect(
    () => () => {
      talking.current = false;
      closeMic();
      const ws = wsRef.current;
      wsRef.current = null;
      ws?.close();
      void ctxRef.current?.close();
    },
    [closeMic],
  );

  // Time into the answer now playing (0 until its audio reports progress).
  const answerTime = answer?.audioUrl && played?.url === answer.audioUrl ? played.ms : 0;
  return { state, answerTime, ask, startTalk, stopTalk, skipAnswer: finish };
}
