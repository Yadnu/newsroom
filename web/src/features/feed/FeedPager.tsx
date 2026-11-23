"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { usePressFeed } from "@/src/api/press";

import { CardSkeleton } from "./CardSkeleton";
import {
  type Step,
  STEP_COOLDOWN_MS,
  clampIndex,
  keyStep,
  shouldPrefetch,
  swipeStep,
  wheelStep,
} from "./pager";
import { StoryCard } from "./StoryCard";

const slide = {
  enter: (dir: Step) => ({ y: dir >= 0 ? "100%" : "-100%", opacity: 0.4 }),
  center: { y: "0%", opacity: 1 },
  exit: (dir: Step) => ({ y: dir >= 0 ? "-30%" : "30%", opacity: 0 }),
};

export function FeedPager() {
  const { stories, isPending, isError, error, refetch, hasNextPage, isFetchingNextPage, fetchNextPage } =
    usePressFeed();
  const [index, setIndex] = useState(0);
  const [dir, setDir] = useState<Step>(1);
  const wheelRest = useRef(0);
  const lockedUntil = useRef(0);
  const touchY = useRef<number | null>(null);
  const count = stories.length;

  const go = useCallback(
    (step: Step) => {
      if (step === 0 || performance.now() < lockedUntil.current) return;
      setIndex((i) => {
        const next = clampIndex(i + step, count);
        if (next !== i) {
          setDir(step);
          lockedUntil.current = performance.now() + STEP_COOLDOWN_MS;
        }
        return next;
      });
    },
    [count],
  );

  useEffect(() => {
    if (shouldPrefetch(index, count, Boolean(hasNextPage)) && !isFetchingNextPage) {
      void fetchNextPage();
    }
  }, [index, count, hasNextPage, isFetchingNextPage, fetchNextPage]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable]")) return;
      const step = keyStep(e.key, e.shiftKey);
      if (step !== 0) {
        e.preventDefault();
        go(step);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go]);

  function onWheel(e: React.WheelEvent) {
    const { step, rest } = wheelStep(wheelRest.current, e.deltaY);
    wheelRest.current = rest;
    go(step);
  }

  if (isPending) return <CardSkeleton />;
  if (isError) {
    return (
      <div role="alert" className="flex h-full flex-col items-center justify-center gap-4 bg-set px-6 text-center text-white">
        <p className="font-display text-2xl uppercase tracking-wide">The press desk is offline</p>
        <p className="max-w-md font-body text-sm text-white/65">
          {error.message}. Start the API with <code>uv run fastapi dev app/main.py</code>, then try
          again.
        </p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="rounded-full bg-white px-5 py-2 font-display text-sm uppercase tracking-widest text-set"
        >
          Try again
        </button>
      </div>
    );
  }
  if (count === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-set px-6 text-center text-white">
        <p className="font-display text-2xl uppercase tracking-wide">No stories yet</p>
        <p className="max-w-md font-body text-sm text-white/65">
          The crawlers haven&apos;t filed anything. Run <code>uv run python -m app.reporter</code>{" "}
          or the worker, then <code>uv run newsroom summarize</code>.
        </p>
      </div>
    );
  }

  const story = stories[clampIndex(index, count)];
  return (
    <section
      aria-roledescription="carousel"
      aria-label="Press stories"
      className="relative h-full w-full touch-none overflow-hidden bg-set"
      onWheel={onWheel}
      onTouchStart={(e) => {
        touchY.current = e.touches[0]?.clientY ?? null;
      }}
      onTouchEnd={(e) => {
        const start = touchY.current;
        const end = e.changedTouches[0]?.clientY;
        touchY.current = null;
        if (start !== null && end !== undefined) go(swipeStep(start, end));
      }}
    >
      <AnimatePresence initial={false} custom={dir} mode="popLayout">
        <motion.div
          key={story.id}
          custom={dir}
          variants={slide}
          initial="enter"
          animate="center"
          exit="exit"
          transition={{ type: "tween", ease: [0.22, 1, 0.36, 1], duration: 0.42 }}
          className="absolute inset-0"
          aria-roledescription="slide"
          aria-label={`Story ${index + 1} of ${count}${hasNextPage ? "+" : ""}`}
        >
          <StoryCard story={story} active />
        </motion.div>
      </AnimatePresence>

      <header className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-between px-4 py-3">
        <span className="pointer-events-auto rounded bg-black/55 px-3 py-1 font-display text-sm uppercase tracking-[0.25em] text-white">
          Newsroom <span className="text-gold">Press</span>
        </span>
        <Link
          href="/archive"
          className="pointer-events-auto rounded bg-black/55 px-3 py-1 font-body text-xs text-white/80 hover:text-white"
        >
          Archive
        </Link>
      </header>

      <nav
        aria-label="Story navigation"
        className="absolute bottom-6 right-4 z-10 hidden flex-col gap-2 sm:flex"
      >
        <PagerButton label="Previous story" onClick={() => go(-1)} disabled={index === 0}>
          ↑
        </PagerButton>
        <PagerButton
          label="Next story"
          onClick={() => go(1)}
          disabled={index >= count - 1 && !hasNextPage}
        >
          ↓
        </PagerButton>
      </nav>
      <p aria-live="polite" className="sr-only">
        {`Story ${index + 1}: ${story.title}`}
      </p>
    </section>
  );
}

function PagerButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className="h-10 w-10 rounded-full bg-black/55 font-body text-lg text-white transition-opacity hover:bg-black/75 disabled:opacity-30"
    >
      {children}
    </button>
  );
}
