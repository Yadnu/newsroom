import type { Metadata } from "next";
import { Suspense } from "react";

import { CardSkeleton } from "@/src/features/feed/CardSkeleton";
import { FeedPager } from "@/src/features/feed/FeedPager";

export const metadata: Metadata = {
  title: "Press",
  description: "The newsroom's latest stories, summarized from the wire. Broadcasts are fact-checked.",
};

export default function PressPage() {
  return (
    <main className="h-full w-full">
      {/* FeedPager reads ?category= (task 9.5); Next needs a Suspense boundary around useSearchParams. */}
      <Suspense fallback={<CardSkeleton />}>
        <FeedPager />
      </Suspense>
    </main>
  );
}
