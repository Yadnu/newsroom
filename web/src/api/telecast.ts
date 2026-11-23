"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { getTelecast, isRunning, startTelecast } from "./client";

const POLL_MS = 2000;

/** Starts (or reuses) the story's telecast once, then polls it until it is ready or failed. */
export function useTelecast(storyId: string) {
  const start = useMutation({ mutationFn: () => startTelecast(storyId) });
  const { mutate, data: started, status } = start;
  useEffect(() => {
    if (status === "idle") mutate();
  }, [mutate, status, storyId]);

  const id = started?.id;
  const poll = useQuery({
    queryKey: ["press", "telecast", id],
    queryFn: () => getTelecast(id as string),
    enabled: Boolean(id),
    initialData: started,
    refetchInterval: (q) => (q.state.data && isRunning(q.state.data.step) ? POLL_MS : false),
  });
  return { start, telecast: poll.data ?? started, error: start.error ?? poll.error, retry: () => start.reset() };
}
