"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { type PressCursor, type PressStory, pressCategories, pressPage } from "./client";

/** The feed, newest first; ``category`` null means every category (task 9.5). */
export function usePressFeed(category: string | null = null) {
  const query = useInfiniteQuery({
    queryKey: ["press", "stories", category],
    queryFn: ({ pageParam }) => pressPage(pageParam, undefined, category),
    initialPageParam: null as PressCursor | null,
    getNextPageParam: (last) => last.next,
    staleTime: 60_000,
  });
  const stories: PressStory[] = query.data?.pages.flatMap((p) => p.stories) ?? [];
  return { ...query, stories };
}

export function usePressCategories() {
  return useQuery({
    queryKey: ["press", "categories"],
    queryFn: () => pressCategories(),
    staleTime: 5 * 60_000,
  });
}
