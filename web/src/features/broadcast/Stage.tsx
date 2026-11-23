"use client";

import { safeHref } from "@/lib/format";
import { type BroadcastScript, activeCaption, inSpan, segmentsAt } from "@/src/broadcast/script";
import { gradientFor } from "@/src/features/feed/look";

/**
 * The plain stage of the player skeleton (task 8.3): everything is positioned from the script and the
 * show time only. The studio, animated anchor, bumper and graphics replace these blocks in 8.4 and 8.5.
 */
export function Stage({
  script,
  time,
  captions,
}: {
  script: BroadcastScript;
  time: number;
  captions: boolean;
}) {
  const at = segmentsAt(script, time);
  const caption = activeCaption(script, time);
  const image = script.imageUrl ? safeHref(script.imageUrl) : undefined;
  const headline = script.lowerThirds.find((l) => l.kind === "headline");
  const factcheck = script.lowerThirds.find((l) => l.kind === "factcheck");

  return (
    <div className="relative h-full w-full overflow-hidden bg-gradient-to-b from-set-2 to-set">
      {at.includes("bumper") && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
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
          {/* Anchor placeholder: the animated anchor arrives in 8.4. */}
          <div aria-hidden className="absolute bottom-0 left-[12%] h-[62%] w-[26%] rounded-t-full bg-white/10" />
          <div aria-hidden className="absolute bottom-0 left-0 h-[18%] w-full bg-black/40" />
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
          {caption.text}
        </p>
      )}
    </div>
  );
}
