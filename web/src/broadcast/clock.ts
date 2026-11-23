// ShowClock: the single source of show time (ms). While speech plays, the <audio> element is the master
// (pause, speed and seeking move everything together); before and after it, and when audio failed
// (captions-only), a wall clock runs at the same rate. Pure apart from the injected media and now().

import type { BroadcastScript } from "./script";

export interface MediaLike {
  currentTime: number; // seconds
  playbackRate: number;
  readonly paused: boolean;
  play(): Promise<void> | void;
  pause(): void;
}

export const MAX_DRIFT_MS = 120;

type Timing = Pick<BroadcastScript, "duration" | "audioOffset" | "audioDuration">;

export class ShowClock {
  playing = false;
  ended = false;
  rate = 1;
  private base = 0;
  private anchoredAt: number;

  constructor(
    private readonly script: Timing,
    private media: MediaLike | null,
    private readonly now: () => number = () => performance.now(),
  ) {
    this.anchoredAt = now();
  }

  get hasMedia(): boolean {
    return this.media !== null;
  }

  time(): number {
    const t = this.playing ? this.base + (this.now() - this.anchoredAt) * this.rate : this.base;
    return Math.min(Math.max(t, 0), this.script.duration);
  }

  private anchor(at: number): void {
    this.base = at;
    this.anchoredAt = this.now();
  }

  private inAudio(t: number): boolean {
    return (
      this.media !== null &&
      t >= this.script.audioOffset &&
      t < this.script.audioOffset + this.script.audioDuration
    );
  }

  play(): void {
    if (this.ended) this.seek(0);
    this.anchor(this.time());
    this.playing = true;
    this.syncMedia(true);
  }

  pause(): void {
    this.anchor(this.time());
    this.playing = false;
    this.media?.pause();
  }

  seek(ms: number): void {
    this.ended = false;
    this.anchor(Math.min(Math.max(ms, 0), this.script.duration));
    this.syncMedia(true);
  }

  setRate(rate: number): void {
    this.anchor(this.time());
    this.rate = rate;
    if (this.media) this.media.playbackRate = rate;
  }

  /** Audio failed to load or play: carry on with captions on the wall clock. */
  detachMedia(): void {
    this.anchor(this.time());
    this.media?.pause();
    this.media = null;
  }

  /** Call once per animation frame. Returns the current show time. */
  tick(): number {
    let t = this.time();
    if (t >= this.script.duration) {
      this.anchor(this.script.duration);
      this.playing = false;
      this.ended = true;
      this.media?.pause();
      return this.script.duration;
    }
    const media = this.media;
    if (this.playing && media && this.inAudio(t) && !media.paused) {
      const fromMedia = this.script.audioOffset + media.currentTime * 1000;
      if (Math.abs(fromMedia - t) > MAX_DRIFT_MS) {
        this.anchor(fromMedia);
        t = fromMedia;
      }
    }
    this.syncMedia(false);
    return t;
  }

  private syncMedia(force: boolean): void {
    const media = this.media;
    if (!media) return;
    const t = this.time();
    if (this.playing && this.inAudio(t)) {
      const want = (t - this.script.audioOffset) / 1000;
      if (force || media.paused) {
        if (force || Math.abs(media.currentTime - want) * 1000 > MAX_DRIFT_MS) {
          media.currentTime = want;
        }
        media.playbackRate = this.rate;
        if (media.paused) void media.play();
      }
    } else if (!media.paused) {
      media.pause();
    } else if (force && this.inAudio(t)) {
      media.currentTime = (t - this.script.audioOffset) / 1000;
    }
  }
}
