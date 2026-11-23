import { beforeEach, describe, expect, test } from "vitest";

import { type MediaLike, ShowClock } from "./clock";

const TIMING = { duration: 30_000, audioOffset: 2500, audioDuration: 20_000 };

class FakeMedia implements MediaLike {
  currentTime = 0;
  playbackRate = 1;
  paused = true;
  plays = 0;
  play(): void {
    this.paused = false;
    this.plays += 1;
  }
  pause(): void {
    this.paused = true;
  }
}

let now = 0;
const clockNow = () => now;

describe("ShowClock", () => {
  beforeEach(() => {
    now = 0;
  });

  test("runs on the wall clock through the bumper, then starts the audio", () => {
    const media = new FakeMedia();
    const clock = new ShowClock(TIMING, media, clockNow);
    clock.play();
    expect(media.paused).toBe(true); // bumper: no speech yet
    now = 2000;
    expect(clock.tick()).toBe(2000);
    now = 2600;
    clock.tick();
    expect(media.paused).toBe(false);
    expect(media.plays).toBe(1);
  });

  test("the audio is the master while speech plays", () => {
    const media = new FakeMedia();
    const clock = new ShowClock(TIMING, media, clockNow);
    clock.seek(5000);
    clock.play();
    expect(media.currentTime).toBeCloseTo(2.5);
    now = 1000;
    media.currentTime = 2.5 + 0.6; // the audio fell behind (buffering): 600 ms instead of 1000
    expect(clock.tick()).toBeCloseTo(5600);
  });

  test("pause freezes show time and the audio together", () => {
    const media = new FakeMedia();
    const clock = new ShowClock(TIMING, media, clockNow);
    clock.seek(4000);
    clock.play();
    now = 500;
    clock.pause();
    expect(media.paused).toBe(true);
    const t = clock.time();
    now = 5000;
    expect(clock.time()).toBe(t);
  });

  test("speed scales the wall clock and the audio", () => {
    const media = new FakeMedia();
    const clock = new ShowClock(TIMING, media, clockNow);
    clock.setRate(1.5);
    clock.play();
    now = 1000;
    expect(clock.time()).toBe(1500);
    expect(media.playbackRate).toBe(1.5);
  });

  test("seek moves the audio; the outro silences it; the end stops the show", () => {
    const media = new FakeMedia();
    const clock = new ShowClock(TIMING, media, clockNow);
    clock.play();
    clock.seek(12_500);
    expect(media.currentTime).toBeCloseTo(10);
    clock.seek(23_000); // outro
    clock.tick();
    expect(media.paused).toBe(true);
    now = 10_000;
    expect(clock.tick()).toBe(30_000);
    expect(clock.ended).toBe(true);
    expect(clock.playing).toBe(false);
    clock.play(); // replay from the start
    expect(clock.time()).toBe(0);
  });

  test("without audio the captions run on the wall clock", () => {
    const media = new FakeMedia();
    const clock = new ShowClock(TIMING, media, clockNow);
    clock.seek(3000);
    clock.play();
    clock.detachMedia();
    expect(clock.hasMedia).toBe(false);
    now = 2000;
    expect(clock.tick()).toBe(5000);
  });
});
