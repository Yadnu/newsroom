"use client";

import { create } from "zustand";

export const RATES = [0.75, 1, 1.25, 1.5] as const;
export type Rate = (typeof RATES)[number];

interface PlayerState {
  captions: boolean; // on by default (accessibility)
  muted: boolean;
  rate: Rate;
  toggleCaptions: () => void;
  toggleMuted: () => void;
  setRate: (rate: Rate) => void;
}

/** Viewer preferences that carry from one telecast to the next. */
export const usePlayer = create<PlayerState>((set) => ({
  captions: true,
  muted: false,
  rate: 1,
  toggleCaptions: () => set((s) => ({ captions: !s.captions })),
  toggleMuted: () => set((s) => ({ muted: !s.muted })),
  setRate: (rate) => set({ rate }),
}));
