import type { Metadata } from "next";

import { FeedPager } from "@/src/features/feed/FeedPager";

export const metadata: Metadata = {
  title: "Press",
  description: "The newsroom's latest stories, summarized from the wire. Broadcasts are fact-checked.",
};

export default function PressPage() {
  return (
    <main className="h-full w-full">
      <FeedPager />
    </main>
  );
}
