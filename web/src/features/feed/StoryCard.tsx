"use client";

import Link from "next/link";
import { useState } from "react";

import type { PressStory } from "@/src/api/client";
import { safeHref } from "@/lib/format";

import { gradientFor, outletsLine, timeAgo } from "./look";

const SOURCES_SHOWN = 3;

export function StoryCard({ story, active }: { story: PressStory; active: boolean }) {
  const [imageFailed, setImageFailed] = useState(false);
  const image = story.image_url && !imageFailed ? safeHref(story.image_url) : undefined;

  return (
    <article
      aria-label={story.title}
      className="relative flex h-full w-full flex-col overflow-hidden bg-set text-white"
    >
      <div className="relative h-[36%] min-h-40 w-full shrink-0 sm:h-[44%]">
        <div aria-hidden className="absolute inset-0" style={{ background: gradientFor(story.id) }} />
        {image && (
          // eslint-disable-next-line @next/next/no-img-element -- publisher thumbnails, any host
          <img
            src={image}
            alt=""
            loading={active ? "eager" : "lazy"}
            referrerPolicy="no-referrer"
            onError={() => setImageFailed(true)}
            className="absolute inset-0 h-full w-full object-cover"
          />
        )}
        <div aria-hidden className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-set" />
        {image && story.image_outlet && (
          <span className="absolute bottom-2 right-3 rounded bg-black/55 px-2 py-0.5 text-[11px] text-white/85">
            Image: {story.image_outlet}
          </span>
        )}
      </div>

      <div className="mx-auto flex min-h-0 w-full max-w-4xl flex-1 flex-col gap-3 px-5 pb-5 pt-3 sm:px-10">
        <p className="font-body text-xs uppercase tracking-[0.18em] text-gold">
          {outletsLine(story.outlets)} · {timeAgo(story.latest_at)}
        </p>
        <h2 className="font-display text-2xl font-semibold uppercase leading-tight tracking-wide text-white sm:text-4xl">
          {story.title}
        </h2>
        {story.summary ? (
          <p className="line-clamp-6 font-body text-[15px] leading-relaxed text-white/85 sm:text-lg [@media(max-height:820px)]:line-clamp-3">{story.summary}</p>
        ) : (
          <p className="font-body text-base italic text-white/55">
            The press desk hasn&apos;t summarized this story yet. The sources are below.
          </p>
        )}
        <p className="font-body text-[11px] text-white/45">
          Press summary from {story.n_sources} sources · not yet fact-checked
        </p>

        <ul className="flex flex-wrap gap-x-4 gap-y-1 font-body text-sm">
          {story.sources.slice(0, SOURCES_SHOWN).map((s) => {
            const href = safeHref(s.url);
            return (
              <li key={s.id}>
                {href ? (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    tabIndex={active ? 0 : -1}
                    className="text-white/70 underline decoration-white/25 underline-offset-4 hover:text-white"
                  >
                    {s.outlet}
                  </a>
                ) : (
                  <span className="text-white/70">{s.outlet}</span>
                )}
              </li>
            );
          })}
        </ul>

        <div className="mt-auto flex items-center gap-3 pt-2">
          <Link
            href={`/watch/${story.id}`}
            tabIndex={active ? 0 : -1}
            className="inline-flex items-center gap-2 rounded-full bg-breaking px-5 py-2.5 font-display text-sm uppercase tracking-widest text-white hover:brightness-110"
          >
            <span aria-hidden>▶</span> Watch broadcast
          </Link>
          <span className="font-body text-xs text-white/55">
            {story.telecast?.step === "ready" ? "Fact-checked broadcast ready" : "Fact-checked before it airs"}
          </span>
        </div>
      </div>
    </article>
  );
}
