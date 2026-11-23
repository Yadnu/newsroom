import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { Player } from "@/components/Player";
import { TracePanel } from "@/components/TracePanel";
import { api, publicWsUrl } from "@/lib/api";
import { shortId, when } from "@/lib/format";

export const metadata: Metadata = { title: "Listen" };

export default function ListenPage(props: PageProps<"/briefings/[id]/listen">) {
  return (
    <Suspense fallback={<p className="muted">Loading briefing…</p>}>
      <Listen {...props} />
    </Suspense>
  );
}

async function Listen({ params, searchParams }: PageProps<"/briefings/[id]/listen">) {
  const { id } = await params;
  const line = (await searchParams).line;
  const selected = typeof line === "string" ? line : undefined;
  const { briefing: b, lines } = await api.briefing(id);

  return (
    <>
      <p className="muted">
        <Link href="/archive">Briefings</Link> /{" "}
        <Link href={`/briefings/${b.id}`} className="mono">
          {shortId(b.id)}
        </Link>{" "}
        / listen
      </p>
      <h1>Briefing of {when(b.created_at)}</h1>
      <p className="sub">
        Sentences light up as the Anchor reads them. Click any sentence to see its claims and
        sources. Greyed sentences were held back by the Standards Desk.
      </p>
      <div className="split">
        <Player
          briefingId={b.id}
          wsUrl={publicWsUrl()}
          selected={selected}
          lines={lines.map((ln) => ({
            id: ln.id,
            order: ln.order,
            text: ln.text,
            story_title: ln.story_title,
          }))}
        />
        <section>
          {selected ? (
            <Suspense key={selected} fallback={<div className="card empty">Loading trace…</div>}>
              <Trace lineId={selected} />
            </Suspense>
          ) : (
            <div className="card empty">Click a sentence to see its claims, verdicts and sources.</div>
          )}
        </section>
      </div>
    </>
  );
}

async function Trace({ lineId }: { lineId: string }) {
  return <TracePanel trace={await api.trace(lineId)} />;
}
