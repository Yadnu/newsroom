// Pure helpers for the live Player (task 4.3). The Anchor streams PCM16 mono chunks plus JSON
// events whose times are on the audio clock (ms of audio sent, decision 0017).

export type AnchorEvent =
  | { type: "start"; briefing_id: string; sample_rate: number; lines: number }
  | {
      type: "line";
      line_id: string;
      order: number;
      text: string;
      start_ms: number;
      kind?: "script" | "answer";
      question_id?: string;
    }
  | { type: "line_end"; line_id: string; end_ms: number; kind?: string; question_id?: string }
  | { type: "paused"; at_ms: number }
  | { type: "resumed"; at_ms: number }
  | { type: "done"; audio_ms: number; completed: boolean }
  | { type: "caller_interim"; text: string }
  | {
      type: "caller_question";
      id: string;
      transcript: string;
      intent: "follow_up" | "background" | "off_topic" | "unknown";
      story_id: string | null;
      story_title: string | null;
      restated: string;
      allowed: boolean;
      screen_category: "ok" | "empty" | "too_long" | "abusive" | "injection" | "off_topic";
      screen_reason: string;
    }
  | { type: "caller_error"; message: string }
  | {
      type: "answer_status";
      question_id: string;
      state: AnswerState;
      lines?: { line_id: string; text: string }[];
      total_ms?: number;
    };

export type AnswerState = "thinking" | "answering" | "unsure" | "declined" | "failed";

export type CallerQuestionEvent = Extract<AnchorEvent, { type: "caller_question" }>;

/** Little-endian signed 16-bit PCM to floats in [-1, 1). */
export function pcm16ToFloat32(bytes: ArrayBuffer): Float32Array<ArrayBuffer> {
  const view = new DataView(bytes);
  const out = new Float32Array(Math.floor(bytes.byteLength / 2));
  for (let i = 0; i < out.length; i++) out[i] = view.getInt16(i * 2, true) / 32768;
  return out;
}

/**
 * Maps the audio clock (ms of audio received) to the AudioContext timeline. Each chunk is
 * scheduled right after the previous one, or a little ahead of "now" after an underrun or a
 * pause, so the mapping is piecewise.
 */
export class AudioClock {
  private segments: { ctxStart: number; clockMs: number }[] = [];
  private nextCtxTime = 0;
  receivedMs = 0;
  readonly sampleRate: number;
  private readonly leadS: number;

  constructor(sampleRate: number, leadS = 0.08) {
    this.sampleRate = sampleRate;
    this.leadS = leadS;
  }

  /** Returns the context time to start this chunk at, and advances the clock. */
  schedule(samples: number, now: number): number {
    const at = Math.max(this.nextCtxTime, now + this.leadS);
    if (at !== this.nextCtxTime || this.segments.length === 0) {
      this.segments.push({ ctxStart: at, clockMs: this.receivedMs });
    }
    const durS = samples / this.sampleRate;
    this.nextCtxTime = at + durS;
    this.receivedMs += durS * 1000;
    return at;
  }

  /** Forget what was scheduled but not yet played (pause): later chunks start fresh. */
  reset(): void {
    this.nextCtxTime = 0;
  }

  /** Audio-clock ms being heard at context time ``now`` (null before the first chunk plays). */
  clockAt(now: number): number | null {
    let i = -1;
    while (i + 1 < this.segments.length && this.segments[i + 1].ctxStart <= now) i++;
    if (i < 0) return null;
    const seg = this.segments[i];
    const segEnd = this.segments[i + 1]?.clockMs ?? this.receivedMs; // audio dropped at a pause
    return Math.round(Math.min(seg.clockMs + (now - seg.ctxStart) * 1000, segEnd));
  }
}

export type TimedLine = { line_id: string; start_ms: number; end_ms: number | null };

/** The line being heard at audio-clock ``ms``: the latest started line that has not ended. */
export function activeLine(lines: TimedLine[], ms: number | null): string | null {
  if (ms == null) return null;
  let hit: string | null = null;
  for (const l of lines) {
    if (l.start_ms <= ms && (l.end_ms == null || ms < l.end_ms)) hit = l.line_id;
  }
  return hit;
}

/** Apply an event to the per-line timing table (a line replayed after a pause is restamped). */
export function applyEvent(lines: TimedLine[], e: AnchorEvent): TimedLine[] {
  if (e.type === "line") {
    return [
      ...lines.filter((l) => l.line_id !== e.line_id),
      { line_id: e.line_id, start_ms: e.start_ms, end_ms: null },
    ];
  }
  if (e.type === "line_end") {
    return lines.map((l) => (l.line_id === e.line_id ? { ...l, end_ms: e.end_ms } : l));
  }
  return lines;
}

/** ws(s)://host for the API, from an http(s) base URL. */
export function wsBase(apiUrl: string): string {
  return apiUrl.replace(/\/$/, "").replace(/^http/, "ws");
}
