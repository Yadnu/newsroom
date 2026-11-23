"use client";

import { useReducedMotion } from "framer-motion";

import { safeHref } from "@/lib/format";
import { mouthAt, withAmplitude, wordAt } from "@/src/broadcast/lipsync";
import { poseAt } from "@/src/broadcast/pose";
import { type BroadcastScript, activeCaption, segmentsAt } from "@/src/broadcast/script";
import { gradientFor } from "@/src/features/feed/look";

import { BRoll, Bumper, LiveBug, LowerThirds, type NextStory, Outro, Ticker } from "./Graphics";
import { StudioScene } from "./StudioScene";

export interface StageProps {
  script: BroadcastScript;
  time: number;
  captions: boolean;
  amplitude?: () => number | null;
  tickerItems?: string[];
  next?: NextStory | null;
  cancelled?: boolean;
  onCancel?: () => void;
  onPlayNext?: () => void;
  onExit?: () => void;
  onReplay?: () => void;
}

const noop = () => undefined;

/**
 * The broadcast stage. Everything is positioned from the script and the show time only: studio and
 * anchor (task 8.4), bumper, lower thirds, B-roll, LIVE bug, ticker and outro (task 8.5). A container
 * (`@container`) so the graphics' cqw sizes follow the stage, not the window.
 */
export function Stage({
  script,
  time,
  captions,
  amplitude,
  tickerItems = [],
  next = null,
  cancelled = false,
  onCancel = noop,
  onPlayNext = noop,
  onExit = noop,
  onReplay = noop,
}: StageProps) {
  const reduced = Boolean(useReducedMotion());
  const pose = poseAt(script, time, reduced);
  const level = script.wordsEstimated && amplitude ? amplitude() : null;
  const mouth = withAmplitude(mouthAt(script.words, time), level);
  const word = wordAt(script.words, time);
  const at = segmentsAt(script, time);
  const caption = activeCaption(script, time);
  const image = script.imageUrl ? safeHref(script.imageUrl) : undefined;
  const onAir = at.includes("body") || at.includes("outro");

  return (
    <div className="@container relative h-full w-full overflow-hidden bg-set">
      <StudioScene time={time} pose={pose} mouth={mouth} reducedMotion={reduced} />

      {onAir && !at.includes("broll") && (
        <div className="absolute right-[5%] top-[12%] w-[42%] shadow-2xl">
          {image ? (
            // eslint-disable-next-line @next/next/no-img-element -- publisher thumbnail, any host
            <img src={image} alt="" referrerPolicy="no-referrer" className="aspect-video w-full rounded-sm object-cover" />
          ) : (
            <div aria-hidden className="aspect-video w-full rounded-sm" style={{ background: gradientFor(script.storyId) }} />
          )}
          <div className="bg-set/90 px-[0.8cqw] py-[0.3cqw] font-display text-[1.1cqw] uppercase tracking-widest text-gold">
            {script.outlets.slice(0, 3).join(" · ")}
          </div>
        </div>
      )}

      <BRoll script={script} t={time} reduced={reduced} />
      {onAir && <LiveBug t={time} />}
      <LowerThirds script={script} t={time} reduced={reduced} />

      {captions && caption && (
        <p
          aria-live="off"
          className="absolute bottom-[8%] left-1/2 w-[84%] -translate-x-1/2 rounded-sm bg-black/80 px-[1cqw] py-[0.4cqw] text-center font-body text-[1.7cqw] leading-snug text-white"
        >
          {caption.words.length
            ? caption.words.map((w, i) => (
                <span key={i} className={w === word ? "text-gold" : undefined}>
                  {i ? " " : ""}
                  {w.text}
                </span>
              ))
            : caption.text}
        </p>
      )}

      {!at.includes("bumper") && <Ticker items={tickerItems} t={time} reduced={reduced} />}
      <Bumper script={script} t={time} reduced={reduced} />
      <Outro
        script={script}
        t={time}
        next={next}
        cancelled={cancelled}
        onCancel={onCancel}
        onPlayNext={onPlayNext}
        onExit={onExit}
        onReplay={onReplay}
      />
    </div>
  );
}
