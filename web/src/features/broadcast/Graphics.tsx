"use client";

// Broadcast graphics (task 8.5). Sizes use container-query units (cqw) so they scale with the 16:9
// stage. Every motion value comes from src/broadcast/graphics.ts as a function of show time.

import { useLayoutEffect, useRef, useState } from "react";

import { safeHref } from "@/lib/format";
import { bumperAt, countdown, kenBurns, pulse, slideIn, tickerOffset } from "@/src/broadcast/graphics";
import type { BroadcastScript, Span } from "@/src/broadcast/script";

export function Bumper({ script, t, reduced }: { script: BroadcastScript; t: number; reduced: boolean }) {
  const bumper = script.segments.find((s) => s.kind === "bumper");
  const b = bumper ? bumperAt(t, bumper, reduced) : null;
  if (!b) return null;
  const breaking = script.banner === "BREAKING NEWS";
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-set/90" style={{ opacity: b.fade }}>
      <svg viewBox="0 0 1600 900" className="absolute inset-0 h-full w-full" aria-hidden>
        {[0, 1, 2].map((i) => (
          <path
            key={i}
            d={`M -100 ${560 + i * 40} C 400 ${380 + i * 30}, 1000 ${700 - i * 20}, 1700 ${300 + i * 60}`}
            fill="none"
            stroke={i === 1 ? "#d7263d" : "#f2b134"}
            strokeWidth={i === 1 ? 10 : 4}
            strokeLinecap="round"
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={1 - b.swoosh}
            opacity={0.85}
          />
        ))}
      </svg>
      <div className="relative flex flex-col items-center gap-[1.5cqw]">
        <span
          className="font-display text-[7cqw] uppercase leading-none tracking-[0.3em] text-white"
          style={{ transform: `scale(${0.7 + 0.3 * b.logo})`, opacity: b.logo }}
        >
          Newsroom
        </span>
        <span
          className={`origin-left px-[1.6cqw] py-[0.4cqw] font-display text-[2.2cqw] uppercase tracking-[0.25em] ${
            breaking ? "bg-breaking text-white" : "bg-gold text-set"
          }`}
          style={{ transform: `scaleX(${b.banner})`, opacity: b.banner > 0 ? 1 : 0 }}
        >
          {script.banner}
        </span>
      </div>
    </div>
  );
}

function LowerThirdBox({ span, t, reduced, children }: { span: Span; t: number; reduced: boolean; children: React.ReactNode }) {
  const m = slideIn(t, span, reduced);
  if (m.opacity <= 0) return null;
  return (
    <div
      className="absolute bottom-[22%] left-[3%] max-w-[64%]"
      style={{ transform: `translateX(${m.x * 110}%)`, opacity: m.opacity }}
    >
      {children}
    </div>
  );
}

export function LowerThirds({ script, t, reduced }: { script: BroadcastScript; t: number; reduced: boolean }) {
  const breaking = script.banner === "BREAKING NEWS";
  return (
    <>
      {script.lowerThirds.map((l) =>
        l.kind === "headline" ? (
          <LowerThirdBox key={l.kind} span={l} t={t} reduced={reduced}>
            <span
              className={`inline-block px-[0.9cqw] py-[0.2cqw] font-display text-[1.2cqw] uppercase tracking-[0.2em] ${
                breaking ? "bg-breaking text-white" : "bg-gold text-set"
              }`}
            >
              {script.banner}
            </span>
            <div className="border-l-[0.5cqw] border-breaking bg-white px-[1.2cqw] py-[0.6cqw] text-set shadow-xl">
              <p className="font-display text-[2.1cqw] uppercase leading-tight">{script.title}</p>
              <p className="font-body text-[1.05cqw] text-set/70">{script.outlets.join(" · ")}</p>
            </div>
          </LowerThirdBox>
        ) : (
          <LowerThirdBox key={l.kind} span={l} t={t} reduced={reduced}>
            <div className="flex items-center gap-[0.8cqw] bg-gold px-[1.2cqw] py-[0.6cqw] text-set shadow-xl">
              <span aria-hidden className="font-display text-[1.8cqw]">✓</span>
              <p className="font-display text-[1.5cqw] uppercase tracking-wider">
                Fact-checked: {script.approved} of {script.claims} claims approved · {script.outlets.length} outlets
              </p>
            </div>
          </LowerThirdBox>
        ),
      )}
    </>
  );
}

export function BRoll({ script, t, reduced }: { script: BroadcastScript; t: number; reduced: boolean }) {
  const span = script.segments.find((s) => s.kind === "broll");
  const image = script.imageUrl ? safeHref(script.imageUrl) : undefined;
  const k = span && image ? kenBurns(t, span, reduced) : null;
  if (!k || !image) return null;
  return (
    <div className="absolute inset-0 overflow-hidden bg-black" style={{ opacity: k.opacity }}>
      {/* eslint-disable-next-line @next/next/no-img-element -- publisher thumbnail, any host */}
      <img
        src={image}
        alt=""
        referrerPolicy="no-referrer"
        className="h-full w-full object-cover"
        style={{ transform: `scale(${k.scale}) translate(${k.x}%, ${k.y}%)` }}
      />
      {script.imageOutlet && (
        <span className="absolute right-[2%] top-[3%] bg-black/55 px-[0.6cqw] font-body text-[0.9cqw] text-white/85">
          Image: {script.imageOutlet}
        </span>
      )}
    </div>
  );
}

export function LiveBug({ t }: { t: number }) {
  const now = new Date();
  const clock = now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return (
    <div className="absolute left-[2.5%] top-[4%] flex items-stretch font-display text-[1.3cqw] uppercase tracking-widest">
      <span className="flex items-center gap-[0.5cqw] bg-breaking px-[0.8cqw] py-[0.25cqw] text-white">
        <span aria-hidden className="inline-block h-[0.7cqw] w-[0.7cqw] rounded-full bg-white" style={{ opacity: pulse(t) }} />
        Live
      </span>
      <span className="bg-black/60 px-[0.8cqw] py-[0.25cqw] tabular-nums text-white">{clock}</span>
    </div>
  );
}

export function Ticker({ items, t, reduced }: { items: string[]; t: number; reduced: boolean }) {
  const content = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = content.current;
    if (!el) return;
    const measure = () => setWidth(el.scrollWidth / 2); // the items are rendered twice for a seamless wrap
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [items]);
  if (!items.length) return null;
  const text = items.join("   •   ") + "   •   ";
  const offset = reduced ? 0 : tickerOffset(t, width);
  return (
    <div className="absolute inset-x-0 bottom-0 flex h-[6%] items-stretch bg-set/95 font-body text-[1.25cqw] text-white">
      <span className="z-10 flex shrink-0 items-center bg-breaking px-[1cqw] font-display uppercase tracking-widest">
        Headlines
      </span>
      <div className="relative min-w-0 flex-1 overflow-hidden" aria-label="Other headlines">
        <div
          ref={content}
          className="absolute left-0 top-1/2 whitespace-nowrap"
          style={{ transform: `translate(${offset}px, -50%)` }}
        >
          <span className="px-[1cqw]">{text}</span>
          <span aria-hidden className="px-[1cqw]">
            {text}
          </span>
        </div>
      </div>
    </div>
  );
}

export interface NextStory {
  title: string;
}

export function Outro({
  script,
  t,
  next,
  cancelled,
  onCancel,
  onPlayNext,
  onExit,
  onReplay,
}: {
  script: BroadcastScript;
  t: number;
  next: NextStory | null;
  cancelled: boolean;
  onCancel: () => void;
  onPlayNext: () => void;
  onExit: () => void;
  onReplay: () => void;
}) {
  const outro = script.segments.find((s) => s.kind === "outro");
  if (!outro || t < outro.start + 1200) return null; // the anchor signs off and nods first
  const left = countdown(t, script.duration);
  const btn = "rounded-full px-[1.6cqw] py-[0.6cqw] font-display text-[1.3cqw] uppercase tracking-widest";
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-set/80">
      <div className="flex max-w-[70%] flex-col items-center gap-[1.2cqw] text-center text-white">
        {next && !cancelled ? (
          <>
            <p className="font-display text-[1.4cqw] uppercase tracking-[0.3em] text-gold">
              Next story in {left}
            </p>
            <p className="font-display text-[3cqw] uppercase leading-tight">{next.title}</p>
            <div className="flex gap-[1cqw]">
              <button type="button" onClick={onPlayNext} className={`${btn} bg-breaking text-white`}>
                Play now
              </button>
              <button type="button" onClick={onCancel} className={`${btn} bg-white/15 text-white`}>
                Cancel
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="font-display text-[3cqw] uppercase tracking-widest">That&apos;s the story</p>
            <div className="flex gap-[1cqw]">
              <button type="button" onClick={onReplay} className={`${btn} bg-white/15 text-white`}>
                Replay
              </button>
              {next && (
                <button type="button" onClick={onPlayNext} className={`${btn} bg-breaking text-white`}>
                  Next story
                </button>
              )}
              <button type="button" onClick={onExit} className={`${btn} bg-white text-set`}>
                Back to the feed
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
