"use client";

import { useReducedMotion } from "framer-motion";

import { wordAt } from "@/src/broadcast/lipsync";
import { type BroadcastScript, activeCaption, segmentsAt } from "@/src/broadcast/script";

import { CaptionText, type NextStory, Outro, Ticker } from "./Graphics";

/**
 * Phones held upright (task 8.6): the 16:9 stage keeps only the picture; the headline, fact-check
 * line, captions, outro card and ticker move here, below it, at readable sizes. Hidden in landscape.
 */
export function PortraitPanel({
  script,
  time,
  captions,
  tickerItems,
  next,
  cancelled,
  onCancel,
  onPlayNext,
  onExit,
  onReplay,
}: {
  script: BroadcastScript;
  time: number;
  captions: boolean;
  tickerItems: string[];
  next: NextStory | null;
  cancelled: boolean;
  onCancel: () => void;
  onPlayNext: () => void;
  onExit: () => void;
  onReplay: () => void;
}) {
  const reduced = Boolean(useReducedMotion());
  const caption = activeCaption(script, time);
  const word = wordAt(script.words, time);
  const outro = script.segments.find((s) => s.kind === "outro");
  const signedOff = outro !== undefined && time >= outro.start + 1200;
  const breaking = script.banner === "BREAKING NEWS";
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-set text-white landscape:hidden">
      {signedOff ? (
        <Outro
          compact
          script={script}
          t={time}
          next={next}
          cancelled={cancelled}
          onCancel={onCancel}
          onPlayNext={onPlayNext}
          onExit={onExit}
          onReplay={onReplay}
        />
      ) : (
        <div className="flex flex-col gap-2 px-4 py-3">
          <span
            className={`self-start px-2 py-0.5 font-display text-[11px] uppercase tracking-[0.2em] ${
              breaking ? "bg-breaking text-white" : "bg-gold text-set"
            }`}
          >
            {script.banner}
          </span>
          <h1 className="font-display text-xl uppercase leading-tight">{script.title}</h1>
          <p className="font-body text-xs text-white/60">{script.outlets.join(" · ")}</p>
          {script.claims > 0 && (
            <p className="font-body text-xs text-gold">
              ✓ Fact-checked: {script.approved} of {script.claims} claims approved
            </p>
          )}
        </div>
      )}
      {captions && !segmentsAt(script, time).includes("bumper") && (
        <p aria-live="off" className="min-h-[4.5rem] px-4 py-2 font-body text-lg leading-snug">
          {caption ? <CaptionText caption={caption} word={word} /> : null}
        </p>
      )}
      <div className="mt-auto">
        <Ticker compact items={tickerItems} t={time} reduced={reduced} />
      </div>
    </div>
  );
}
