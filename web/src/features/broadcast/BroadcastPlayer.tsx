"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import type { TelecastView } from "@/src/api/client";
import { usePressFeed } from "@/src/api/press";
import { useTelecast } from "@/src/api/telecast";
import { useAmplitude } from "@/src/audio/useAmplitude";
import { useShowClock } from "@/src/audio/useShowClock";
import { buildBroadcastScript } from "@/src/broadcast/script";
import { usePlayer } from "@/src/store/player";

import { Controls } from "./Controls";
import { Preparing, TelecastFailed } from "./Preparing";
import { Stage } from "./Stage";

const SEEK_STEP_MS = 5000;

/** /watch/[storyId]: start (or reuse) the story's telecast, show progress, then play it. */
export function BroadcastPlayer({ storyId }: { storyId: string }) {
  const router = useRouter();
  const { telecast, error, retry } = useTelecast(storyId);
  const { stories } = usePressFeed();
  const index = stories.findIndex((s) => s.id === storyId);
  const title = telecast?.story?.title ?? stories[index]?.title ?? "";
  const prevId = index > 0 ? stories[index - 1].id : undefined;
  const nextId = index >= 0 && index < stories.length - 1 ? stories[index + 1].id : undefined;

  const exit = () => router.push("/");
  const go = (id: string | undefined) => (id ? () => router.push(`/watch/${id}`) : undefined);

  if (error) {
    return <TelecastFailed telecast={telecast} message={error.message} onRetry={retry} />;
  }
  if (telecast?.step === "failed") {
    return (
      <TelecastFailed
        telecast={telecast}
        message={telecast.error ?? "The broadcast could not be prepared."}
        onRetry={retry}
      />
    );
  }
  if (telecast?.step !== "ready") return <Preparing telecast={telecast} title={title} />;
  return (
    <Show
      key={telecast.id}
      telecast={telecast}
      onExit={exit}
      onPrev={go(prevId)}
      onNext={go(nextId)}
    />
  );
}

function Show({
  telecast,
  onExit,
  onPrev,
  onNext,
}: {
  telecast: TelecastView;
  onExit: () => void;
  onPrev?: () => void;
  onNext?: () => void;
}) {
  const script = useMemo(() => buildBroadcastScript(telecast), [telecast]);
  const [audio, setAudio] = useState<HTMLAudioElement | null>(null);
  const show = useShowClock(script, script.audioUrl ? audio : null);
  const amplitude = useAmplitude(audio, script.wordsEstimated && !show.audioFailed, show.playing);
  const { captions, muted, rate, toggleCaptions, toggleMuted } = usePlayer();
  const { setRate, toggle, seek, replay, time } = show;

  useEffect(() => setRate(rate), [rate, setRate]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.target as HTMLElement | null)?.closest("input, select, textarea")) return;
      const keys: Record<string, () => void> = {
        " ": toggle,
        k: toggle,
        m: toggleMuted,
        c: toggleCaptions,
        r: replay,
        ArrowLeft: () => seek(time - SEEK_STEP_MS),
        ArrowRight: () => seek(time + SEEK_STEP_MS),
        Escape: onExit,
        ...(onNext ? { n: onNext } : {}),
        ...(onPrev ? { p: onPrev } : {}),
      };
      const action = keys[e.key];
      if (action) {
        e.preventDefault();
        action();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle, toggleMuted, toggleCaptions, replay, seek, time, onExit, onNext, onPrev]);

  return (
    <div className="flex h-full w-full flex-col bg-black">
      {script.audioUrl && (
        <audio ref={setAudio} src={script.audioUrl} preload="auto" muted={muted} />
      )}
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <div
          role="region"
          aria-label={`Broadcast: ${script.title}`}
          className="relative aspect-video max-h-full w-full max-w-[calc((100vh-5.5rem)*16/9)]"
        >
          <Stage script={script} time={show.time} captions={captions} amplitude={amplitude} />
          {show.blocked && (
            <button
              type="button"
              onClick={show.play}
              className="absolute inset-0 flex items-center justify-center bg-black/60 font-display text-2xl uppercase tracking-widest text-white"
            >
              ▶ Play broadcast
            </button>
          )}
        </div>
      </div>
      <Controls
        time={show.time}
        duration={script.duration}
        playing={show.playing}
        audioFailed={show.audioFailed}
        onToggle={toggle}
        onReplay={replay}
        onSeek={seek}
        onRate={setRate}
        onPrev={onPrev}
        onNext={onNext}
        onExit={onExit}
      />
      <p aria-live="polite" className="sr-only">
        {show.ended ? "Broadcast ended." : ""}
      </p>
    </div>
  );
}
