"use client";

import { useQuery } from "@tanstack/react-query";

import { getTelecast, isRunning, startTelecast } from "./client";

const POLL_MS = 2000;

/**
 * Starts (or reuses) the story's telecast, then polls it until it is ready or failed.
 * The start is a deduplicated query, not a mutation: React running effects twice in development, or
 * two components mounting, send one request (the server also locks per story).
 */
export function useTelecast(storyId: string) {
  const start = useQuery({
    queryKey: ["press", "telecast-start", storyId],
    queryFn: () => startTelecast(storyId),
    staleTime: Infinity,
    gcTime: 0, // leaving and coming back asks again (the server reuses a recent telecast)
    retry: false,
    refetchOnWindowFocus: false,
  });
  const started = start.data;
  const id = started?.id;
  const poll = useQuery({
    queryKey: ["press", "telecast", id],
    queryFn: () => getTelecast(id as string),
    enabled: Boolean(id),
    initialData: started,
    refetchInterval: (q) => (q.state.data && isRunning(q.state.data.step) ? POLL_MS : false),
  });
  return {
    telecast: poll.data ?? started,
    error: start.error ?? poll.error,
    retry: () => void start.refetch(),
  };
}
