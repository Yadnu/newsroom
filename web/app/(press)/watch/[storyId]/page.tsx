import type { Metadata } from "next";
import { Suspense } from "react";

import { BroadcastPlayer } from "@/src/features/broadcast/BroadcastPlayer";

export const metadata: Metadata = { title: "Broadcast" };

export default function WatchPage(props: PageProps<"/watch/[storyId]">) {
  return (
    <main className="h-full w-full">
      <Suspense fallback={null}>
        <Watch {...props} />
      </Suspense>
    </main>
  );
}

async function Watch({ params }: PageProps<"/watch/[storyId]">) {
  const { storyId } = await params;
  return <BroadcastPlayer storyId={storyId} />;
}
