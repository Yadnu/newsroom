// The data-driven broadcast timeline (FRONTEND_PLAN.md section 4): every component reads its timing
// from a BroadcastScript built here, on one "show time" axis in milliseconds. Pure; see script.test.ts.

import type { TelecastView } from "@/src/api/client";

import { type TimedWord, estimateWords } from "./lipsync";

export const BUMPER_MS = 2500; // intro bumper before the anchor speaks
export const INTRO_MS = 1500; // the anchor looks up from the papers as speech starts
export const OUTRO_MS = 5000; // sign-off and the "next story" countdown
export const BREAKING_MAX_AGE_MS = 3 * 3600_000;
export const BREAKING_MIN_OUTLETS = 3;

export type SegmentKind = "bumper" | "intro" | "body" | "broll" | "outro";

export interface Span {
  start: number;
  end: number;
}

export interface Segment extends Span {
  kind: SegmentKind;
}

export interface Caption extends Span {
  lineId: string;
  text: string;
  words: TimedWord[]; // show time; from the TTS, or estimated from the line's length
  estimated: boolean;
}

export interface LowerThird extends Span {
  kind: "headline" | "factcheck";
}

export interface BroadcastScript {
  telecastId: string;
  storyId: string;
  title: string;
  imageUrl: string | null;
  imageOutlet: string | null;
  outlets: string[];
  banner: "BREAKING NEWS" | "TOP STORY";
  approved: number;
  claims: number;
  audioUrl: string | null;
  audioOffset: number; // show time at which audio time 0 plays
  audioDuration: number;
  duration: number;
  segments: Segment[]; // bumper, intro, body, outro in order; broll (if any) overlaps body
  captions: Caption[];
  words: TimedWord[]; // every caption's words in order (lip sync)
  wordsEstimated: boolean; // true if any line had no TTS word timings
  lowerThirds: LowerThird[];
  nodAt: number; // the anchor nods as the last line ends
}

export function isBreaking(latestAt: string, outlets: number, now: Date): boolean {
  const age = now.getTime() - new Date(latestAt).getTime();
  return age >= 0 && age <= BREAKING_MAX_AGE_MS && outlets >= BREAKING_MIN_OUTLETS;
}

function clampSpan(start: number, end: number, within: Span): Span {
  const s = Math.max(within.start, Math.min(start, within.end));
  return { start: s, end: Math.max(s, Math.min(end, within.end)) };
}

/** A ready telecast -> the show. Without lines (captions-only) the body still lasts duration_ms. */
export function buildBroadcastScript(t: TelecastView, now: Date = new Date()): BroadcastScript {
  const lines = [...(t.lines ?? [])].sort((a, b) => a.start_ms - b.start_ms);
  const lastEnd = lines.length ? lines[lines.length - 1].end_ms : 0;
  const audioDuration = Math.max(t.duration_ms ?? 0, lastEnd);
  const body: Span = { start: BUMPER_MS, end: BUMPER_MS + audioDuration };
  const duration = body.end + OUTRO_MS;

  const segments: Segment[] = [
    { kind: "bumper", start: 0, end: BUMPER_MS },
    { kind: "intro", ...clampSpan(body.start, body.start + INTRO_MS, body) },
    { kind: "body", ...body },
    { kind: "outro", start: body.end, end: duration },
  ];
  const story = t.story ?? null;
  if (story?.image_url && audioDuration >= 15_000) {
    // B-roll cut: from the caption boundary nearest 40% of the body, for a quarter (max 8 s).
    const target = body.start + audioDuration * 0.4;
    const boundaries = lines.map((l) => body.start + l.start_ms);
    const start = boundaries.length
      ? boundaries.reduce((best, b) => (Math.abs(b - target) < Math.abs(best - target) ? b : best))
      : target;
    const length = Math.min(8000, audioDuration * 0.25);
    segments.push({ kind: "broll", ...clampSpan(start, start + length, body) });
  }

  const captions: Caption[] = lines.map((l) => {
    const start = body.start + l.start_ms;
    const end = body.start + l.end_ms;
    const real = (l.words ?? []).map((w) => ({
      text: w.text,
      start: body.start + w.start_ms,
      end: body.start + w.end_ms,
    }));
    return {
      lineId: l.id,
      text: l.text,
      start,
      end,
      words: real.length ? real : estimateWords(l.text, start, end),
      estimated: real.length === 0,
    };
  });
  const mid = body.start + audioDuration * 0.55;
  const candidates: LowerThird[] = [
    { kind: "headline", ...clampSpan(body.start + 800, body.start + 7800, body) },
    { kind: "factcheck", ...clampSpan(mid, mid + 6000, body) },
  ];
  const lowerThirds = candidates.filter((l) => l.end > l.start);

  const verdicts: Record<string, number> = t.verdicts ?? {};
  const claims = Object.values(verdicts).reduce((a, b) => a + b, 0);
  return {
    telecastId: t.id,
    storyId: t.story_id,
    title: story?.title ?? "",
    imageUrl: story?.image_url ?? null,
    imageOutlet: story?.image_outlet ?? null,
    outlets: story?.outlets ?? [],
    banner:
      story && isBreaking(story.latest_at, story.outlets.length, now) ? "BREAKING NEWS" : "TOP STORY",
    approved: verdicts.approved ?? 0,
    claims,
    audioUrl: t.audio_url ?? null,
    audioOffset: body.start,
    audioDuration,
    duration,
    segments,
    captions,
    words: captions.flatMap((c) => c.words),
    wordsEstimated: captions.some((c) => c.estimated),
    lowerThirds,
    nodAt: body.end,
  };
}

/** The caption on screen at show time `t` (null between lines and outside the body). */
export function activeCaption(script: BroadcastScript, t: number): Caption | null {
  let lo = 0;
  let hi = script.captions.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const c = script.captions[mid];
    if (t < c.start) hi = mid - 1;
    else if (t >= c.end) lo = mid + 1;
    else return c;
  }
  return null;
}

export function segmentsAt(script: BroadcastScript, t: number): SegmentKind[] {
  return script.segments.filter((s) => t >= s.start && t < s.end).map((s) => s.kind);
}

export function inSpan(span: Span, t: number): boolean {
  return t >= span.start && t < span.end;
}
