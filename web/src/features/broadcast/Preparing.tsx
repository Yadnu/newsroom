"use client";

import { motion } from "framer-motion";
import Link from "next/link";

import { TELECAST_STEPS, type TelecastView } from "@/src/api/client";

const LABELS: Record<(typeof TELECAST_STEPS)[number], string> = {
  queued: "Booking the studio",
  writing: "Writing the script",
  checking: "Fact-checking every claim",
  clearing: "Standards desk review",
  voicing: "Recording the anchor",
};

/** "Going to air…": the real pipeline steps of the telecast job. */
export function Preparing({ telecast, title }: { telecast: TelecastView | undefined; title: string }) {
  const current = telecast?.step ?? "queued";
  const at = TELECAST_STEPS.indexOf(current as (typeof TELECAST_STEPS)[number]);
  return (
    <div className="flex h-full flex-col items-center justify-center gap-8 bg-set px-6 text-center text-white">
      <div className="flex items-center gap-3">
        <motion.span
          aria-hidden
          className="h-3 w-3 rounded-full bg-breaking"
          animate={{ opacity: [1, 0.25, 1] }}
          transition={{ duration: 1.2, repeat: Infinity }}
        />
        <span className="font-display text-sm uppercase tracking-[0.3em] text-white/70">
          Going to air
        </span>
      </div>
      {title && (
        <h1 className="max-w-3xl font-display text-2xl uppercase leading-tight tracking-wide sm:text-4xl">
          {title}
        </h1>
      )}
      <ol aria-label="Broadcast preparation" className="flex w-full max-w-sm flex-col gap-2 text-left">
        {TELECAST_STEPS.map((step, i) => {
          const done = i < at;
          const active = i === at;
          return (
            <li
              key={step}
              aria-current={active ? "step" : undefined}
              className={`flex items-center gap-3 font-body text-sm ${
                done ? "text-white/60" : active ? "text-white" : "text-white/30"
              }`}
            >
              <span
                aria-hidden
                className={`flex h-5 w-5 items-center justify-center rounded-full border text-[10px] ${
                  done ? "border-gold bg-gold text-set" : active ? "border-white" : "border-white/30"
                }`}
              >
                {done ? "✓" : ""}
              </span>
              {LABELS[step]}
              {active && <span className="sr-only"> (in progress)</span>}
            </li>
          );
        })}
      </ol>
      <p className="max-w-md font-body text-xs text-white/45">
        Only claims the editor approves against their sources go on air. This takes a minute or two.
      </p>
      <Link href="/" className="font-body text-sm text-white/60 underline underline-offset-4">
        Back to the feed
      </Link>
    </div>
  );
}

export function TelecastFailed({
  telecast,
  message,
  onRetry,
}: {
  telecast: TelecastView | undefined;
  message: string;
  onRetry: () => void;
}) {
  return (
    <div role="alert" className="flex h-full flex-col items-center justify-center gap-4 bg-set px-6 text-center text-white">
      <p className="font-display text-2xl uppercase tracking-wide">This story didn&apos;t make air</p>
      <p className="max-w-md font-body text-sm text-white/70">{message}</p>
      <div className="flex flex-wrap items-center justify-center gap-4">
        <button
          type="button"
          onClick={onRetry}
          className="rounded-full bg-white px-5 py-2 font-display text-sm uppercase tracking-widest text-set"
        >
          Try again
        </button>
        {telecast?.briefing_id && (
          <Link
            href={`/briefings/${telecast.briefing_id}`}
            className="font-body text-sm text-white/70 underline underline-offset-4"
          >
            See the fact-check in the Archive
          </Link>
        )}
        <Link href="/" className="font-body text-sm text-white/70 underline underline-offset-4">
          Back to the feed
        </Link>
      </div>
    </div>
  );
}
