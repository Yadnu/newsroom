"use client";

import { useReducedMotion } from "framer-motion";

import { safeHref } from "@/lib/format";
import { mouthAt, withAmplitude, wordAt } from "@/src/broadcast/lipsync";
import { poseAt } from "@/src/broadcast/pose";
import { type BroadcastScript, activeCaption, inSpan, segmentsAt } from "@/src/broadcast/script";
import { gradientFor } from "@/src/features/feed/look";

import { StudioScene } from "./StudioScene";

/**
 * The broadcast stage: everything is positioned from the script and the show time only. Studio,
 * anchor and lip sync since task 8.4; bumper, lower thirds and outro graphics are polished in 8.5.
 */
export function Stage({
  script,
  time,
  captions,
  amplitude,
}: {
  script: BroadcastScript;
  time: number;
  captions: boolean;
  amplitude?: () => number | null;
}) {
  const reduced = Boolean(useReducedMotion());
  const pose = poseAt(script, time, reduced);
  const level = script.wordsEstimated && amplitude ? amplitude() : null;
  const mouth = withAmplitude(mouthAt(script.words, time), level);
  const word = wordAt(script.words, time);
  const at = segmentsAt(script, time);
  const caption = activeCaption(script, time);
  const image = script.imageUrl ? safeHref(script.imageUrl) : undefined;
  const headline = script.lowerThirds.find((l) => l.kind === "headline");
  const factcheck = script.lowerThirds.find((l) => l.kind === "factcheck");

  return (
    <div className="relative h-full w-full overflow-hidden bg-set">
      <StudioScene time={time} pose={pose} mouth={mouth} reducedMotion={reduced} />
      {at.includes("bumper") && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-set/85">
          <span className="font-display text-5xl uppercase tracking-[0.3em] text-white sm:text-7xl">
            Newsroom
          </span>
          <span
            className={`px-4 py-1 font-display text-lg uppercase tracking-[0.25em] text-white ${
              script.banner === "BREAKING NEWS" ? "bg-breaking" : "bg-gold text-set"
            }`}
          >
            {script.banner}
          </span>
        </div>
      )}

      {(at.includes("body") || at.includes("outro")) && (
        <>
          {image ? (
            // eslint-disable-next-line @next/next/no-img-element -- publisher thumbnail, any host
            <img
              src={image}
              alt=""
              referrerPolicy="no-referrer"
              className="absolute right-[6%] top-[14%] aspect-video w-[42%] rounded object-cover shadow-2xl"
            />
          ) : (
            <div
              aria-hidden
              className="absolute right-[6%] top-[14%] aspect-video w-[42%] rounded shadow-2xl"
              style={{ background: gradientFor(script.storyId) }}
            />
          )}
        </>
      )}

      {at.includes("broll") && image && (
        // eslint-disable-next-line @next/next/no-img-element -- publisher thumbnail, any host
        <img src={image} alt="" referrerPolicy="no-referrer" className="absolute inset-0 h-full w-full object-cover" />
      )}

      {headline && inSpan(headline, time) && (
        <div className="absolute bottom-[22%] left-[4%] max-w-[80%] bg-white px-4 py-2 text-set">
          <p className="font-display text-lg uppercase leading-tight sm:text-2xl">{script.title}</p>
          <p className="font-body text-xs text-set/70">{script.outlets.join(" · ")}</p>
        </div>
      )}
      {factcheck && inSpan(factcheck, time) && (
        <div className="absolute bottom-[22%] left-[4%] bg-gold px-4 py-2 font-display text-sm uppercase tracking-wider text-set">
          Fact-checked: {script.approved} of {script.claims} claims approved · {script.outlets.length} outlets
        </div>
      )}

      {at.includes("outro") && (
        <div className="absolute inset-0 flex items-center justify-center bg-set/80">
          <p className="font-display text-3xl uppercase tracking-widest text-white">That&apos;s the story</p>
        </div>
      )}

      {captions && caption && (
        <p
          aria-live="off"
          className="absolute bottom-[4%] left-1/2 w-[86%] -translate-x-1/2 rounded bg-black/75 px-3 py-1.5 text-center font-body text-sm leading-snug text-white sm:text-lg"
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
    </div>
  );
}
