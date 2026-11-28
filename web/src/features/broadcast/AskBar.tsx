"use client";

import { type FormEvent, type KeyboardEvent, useState } from "react";

import { type AskState, answerLineAt, isBusy } from "@/src/broadcast/questions";

export interface AskBarProps {
  state: AskState;
  answerTime: number;
  onAsk: (text: string) => void;
  onTalkStart: () => void;
  onTalkEnd: () => void;
  onSkip: () => void;
}

const STATUS: Record<AskState["status"], string> = {
  idle: "",
  listening: "Listening…",
  checking: "Screening your question…",
  thinking: "Checking the sources…",
  answering: "",
};

const BTN =
  "shrink-0 rounded px-3 py-1.5 font-body text-sm text-white/90 hover:bg-white/10 disabled:opacity-40";

/** Ask during a telecast (task 9.6): type a question, or hold the mic button and speak. */
export function AskBar({ state, answerTime, onAsk, onTalkStart, onTalkEnd, onSkip }: AskBarProps) {
  const [text, setText] = useState("");
  const busy = isBusy(state);
  const listening = state.status === "listening";

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim() || busy) return;
    onAsk(text);
    setText("");
  };
  const holdKey = (e: KeyboardEvent, start: boolean) => {
    if (e.key !== " " && e.key !== "Enter") return;
    e.preventDefault();
    e.stopPropagation(); // space is also play/pause
    if (start && !e.repeat) onTalkStart();
    else if (!start) onTalkEnd();
  };

  const answer = state.answer;
  const current = answer ? answerLineAt(answer.lines, answerTime) : null;
  const status = STATUS[state.status];

  return (
    <section aria-label="Ask about this story" className="flex flex-col gap-2 bg-black/80 px-3 py-2 text-white">
      <form onSubmit={submit} className="flex items-center gap-1.5">
        <label className="sr-only" htmlFor="ask-input">
          Type a question about this story
        </label>
        <input
          id="ask-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={500}
          disabled={busy}
          placeholder="Ask about this story…"
          className="min-w-0 flex-1 rounded bg-white/10 px-3 py-1.5 font-body text-sm text-white placeholder:text-white/50 disabled:opacity-50"
        />
        <button type="submit" className={BTN} disabled={busy || !text.trim()}>
          Ask
        </button>
        <button
          type="button"
          aria-pressed={listening}
          aria-label="Hold to ask by voice"
          disabled={busy && !listening}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            onTalkStart();
          }}
          onPointerUp={onTalkEnd}
          onPointerCancel={onTalkEnd}
          onKeyDown={(e) => holdKey(e, true)}
          onKeyUp={(e) => holdKey(e, false)}
          onContextMenu={(e) => e.preventDefault()}
          className={`${BTN} touch-none select-none ${listening ? "bg-[var(--color-breaking)] text-white" : ""}`}
        >
          🎙<span className="hidden sm:inline"> {listening ? "Listening" : "Hold to ask"}</span>
        </button>
      </form>

      <div aria-live="polite" className="font-body text-sm">
        {(status || state.note) && (
          <p className="text-white/80">
            {state.heard && state.status !== "idle" && <span className="text-white">“{state.heard}” </span>}
            {status}
            {state.note && <span className="inline-block first-letter:uppercase">{state.note}</span>}
          </p>
        )}
        {answer && (
          <div className="mt-1 rounded border-l-2 border-gold bg-white/5 px-3 py-2">
            <p className="text-xs uppercase tracking-wider text-gold">
              {answer.unsure ? "Not confirmed" : "Answer · fact-checked against the story's sources"}
              {state.question?.restated && (
                <span className="normal-case tracking-normal text-white/60"> · {state.question.restated}</span>
              )}
            </p>
            <p className="mt-1">
              {answer.lines.map((ln) => (
                <span
                  key={ln.line_id}
                  className={!current || current.line_id === ln.line_id || state.status !== "answering" ? "text-white" : "text-white/50"}
                >
                  {ln.text}{" "}
                </span>
              ))}
            </p>
            {state.status === "answering" && (
              <button type="button" onClick={onSkip} className="mt-1 font-body text-xs text-white/70 underline hover:text-white">
                Skip answer and resume
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
