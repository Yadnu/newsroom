"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { type PressCursor, type PressStory, pressPage } from "./client";

export function usePressFeed() {
  const query = useInfiniteQuery({
    queryKey: ["press", "stories"],
    queryFn: ({ pageParam }) => pressPage(pageParam),
    initialPageParam: null as PressCursor | null,
    getNextPageParam: (last) => last.next,
    staleTime: 60_000,
  });
  const stories: PressStory[] = query.data?.pages.flatMap((p) => p.stories) ?? [];
  return { ...query, stories };
}
