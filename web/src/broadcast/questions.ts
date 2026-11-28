// Questions during a telecast (task 9.6, decision 0031). The viewer types or holds the mic; the
// server classifies, screens, fact-checks and voices an answer over
// /press/telecasts/{id}/questions. Pure state; see questions.test.ts.

import type { CallerQuestionEvent } from "@/lib/player";

export interface AnswerLine {
  line_id: string;
  text: string;
  start_ms: number | null; // on the answer audio's clock; null when it could not be voiced
  end_ms: number | null;
}

export type QuestionEvent =
  | { type: "caller_interim"; text: string }
  | CallerQuestionEvent
  | { type: "caller_error"; message: string }
  | {
      type: "answer_status";
      question_id: string;
      state: "thinking" | "answering" | "unsure" | "declined" | "failed";
      lines?: AnswerLine[];
      audio_url?: string | null;
      duration_ms?: number | null;
    };

export type AskAction =
  | QuestionEvent
  | { type: "listening" } // mic opened
  | { type: "sent"; text: string } // a typed question went out
  | { type: "answer_done" } // the answer finished playing (or was skipped)
  | { type: "closed" }; // the socket dropped

export type AskStatus = "idle" | "listening" | "checking" | "thinking" | "answering";

export interface AskState {
  status: AskStatus;
  heard: string; // words heard so far, or the typed question
  question: CallerQuestionEvent | null;
  answer: { lines: AnswerLine[]; audioUrl: string | null; durationMs: number; unsure: boolean } | null;
  note: string | null; // why nothing is being answered, for the viewer
}

export const IDLE: AskState = { status: "idle", heard: "", question: null, answer: null, note: null };

const SCREEN_NOTE: Partial<Record<CallerQuestionEvent["screen_category"], string>> = {
  empty: "That was too short to answer. Try a full question.",
  too_long: "That question is too long. Try asking it in one sentence.",
  abusive: "That question was not answered.",
  injection: "That reads as instructions, not a question, so it was not answered.",
  off_topic: "That is outside this story. Ask about the story on air.",
};

/** What the viewer is told when a question is declined. */
export function declineNote(q: CallerQuestionEvent | null): string {
  if (q && !q.allowed) return SCREEN_NOTE[q.screen_category] ?? "That question was not answered.";
  if (q?.intent === "off_topic") return SCREEN_NOTE.off_topic as string;
  return "That question could not be answered here.";
}

/** Busy states hold the telecast paused and block a second question. */
export function isBusy(s: AskState): boolean {
  return s.status !== "idle";
}

export function askReducer(s: AskState, a: AskAction): AskState {
  switch (a.type) {
    case "listening":
      return { ...IDLE, status: "listening" };
    case "sent":
      return { ...IDLE, status: "checking", heard: a.text };
    case "caller_interim":
      return s.status === "listening" ? { ...s, heard: a.text } : s;
    case "caller_question":
      return { ...s, status: "checking", heard: a.transcript, question: a, note: null };
    case "caller_error":
      return { ...IDLE, note: a.message };
    case "answer_status": {
      if (s.question && a.question_id !== s.question.id) return s; // a stale answer
      if (a.state === "thinking") return { ...s, status: "thinking" };
      if (a.state === "declined") return { ...IDLE, heard: s.heard, question: s.question, note: declineNote(s.question) };
      if (a.state === "failed") {
        return { ...IDLE, heard: s.heard, question: s.question, note: "Could not answer just now. The broadcast continues." };
      }
      const lines = a.lines ?? [];
      return {
        ...s,
        status: "answering",
        answer: {
          lines,
          audioUrl: a.audio_url ?? null,
          durationMs: a.duration_ms ?? captionMs(lines),
          unsure: a.state === "unsure",
        },
      };
    }
    case "answer_done":
      return s.status === "answering" ? { ...IDLE, heard: s.heard, question: s.question, answer: s.answer } : s;
    case "closed":
      return isBusy(s) ? { ...IDLE, note: "Lost the connection to the newsroom. Try asking again." } : s;
  }
}

const READ_MS_PER_WORD = 330; // an unvoiced answer stays on screen about as long as it takes to read

function captionMs(lines: AnswerLine[]): number {
  const words = lines.reduce((n, l) => n + l.text.split(/\s+/).filter(Boolean).length, 0);
  return Math.max(3000, words * READ_MS_PER_WORD);
}

/** The answer line being spoken at `ms` (every line when unvoiced: no timings to follow). */
export function answerLineAt(lines: AnswerLine[], ms: number): AnswerLine | null {
  const timed = lines.filter((l) => l.start_ms != null && l.end_ms != null);
  if (!timed.length) return null;
  let current: AnswerLine | null = null;
  for (const l of timed) if ((l.start_ms as number) <= ms) current = l;
  return current ?? timed[0];
}

/** ws(s):// URL of a telecast's question socket. */
export function questionsUrl(wsBase: string, telecastId: string): string {
  return `${wsBase.replace(/\/$/, "")}/press/telecasts/${encodeURIComponent(telecastId)}/questions`;
}
