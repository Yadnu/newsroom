import Link from "next/link";
import { Suspense } from "react";

import { RejectionTable } from "@/components/RejectionTable";
import { TracePanel } from "@/components/TracePanel";
import { VerdictCounts, VerdictDots } from "@/components/Verdicts";
import { api, type LineSummary } from "@/lib/api";
import { int, ms, shortId, usd, when } from "@/lib/format";

export default function BriefingPage(props: PageProps<"/briefings/[id]">) {
  return (
    <Suspense fallback={<p className="muted">Loading briefing…</p>}>
      <Briefing {...props} />
    </Suspense>
  );
}

async function Briefing({ params, searchParams }: PageProps<"/briefings/[id]">) {
  const { id } = await params;
  const line = (await searchParams).line;
  const selected = typeof line === "string" ? line : undefined;
  const { briefing: b, lines, stages } = await api.briefing(id);

  return (
    <>
      <p className="muted">
        <Link href="/">Briefings</Link> / <span className="mono">{shortId(b.id)}</span>
      </p>
      <h1>Briefing of {when(b.created_at)}</h1>
      <p>
        <Link href={`/briefings/${b.id}/listen`}>▶ Listen to this briefing</Link>
      </p>
      <p className="sub">
        {b.target_minutes} minutes · {b.status} · <VerdictCounts verdicts={b.verdicts} />
      </p>

      <div className="stats">
        <Stat label="Wall time" value={ms(b.wall_ms)} />
        <Stat label="Cost" value={usd(b.cost_usd)} />
        <Stat label="Tokens in / out" value={`${int(b.tokens_in)} / ${int(b.tokens_out)}`} />
        <Stat label="Lines" value={String(b.lines)} />
      </div>

      <div className="split">
        <section>
          <h2>Script</h2>
          <div className="card">
            {lines.length ? (
              <Script lines={lines} briefingId={b.id} selected={selected} />
            ) : (
              <p className="empty">This briefing has no script lines.</p>
            )}
          </div>
        </section>
        <section>
          <h2>Trace</h2>
          {selected ? (
            <Suspense key={selected} fallback={<div className="card empty">Loading trace…</div>}>
              <Trace lineId={selected} />
            </Suspense>
          ) : (
            <div className="card empty">Click a sentence to see its claims, verdicts and sources.</div>
          )}
        </section>
      </div>

      <h2>Stages</h2>
      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>Component</th>
              <th className="num">Steps</th>
              <th className="num">Latency</th>
              <th className="num">LLM calls</th>
              <th className="num">LLM time (summed)</th>
              <th className="num">Tokens</th>
              <th className="num">Cost</th>
              <th className="num">Errors</th>
            </tr>
          </thead>
          <tbody>
            {stages.map((s) => (
              <tr key={s.component}>
                <td>{s.component}</td>
                <td className="num">{s.steps}</td>
                <td className="num">{ms(s.latency_ms)}</td>
                <td className="num">{s.llm_calls}</td>
                <td className="num">{ms(s.llm_ms)}</td>
                <td className="num">{int(s.tokens_in + s.tokens_out)}</td>
                <td className="num">{usd(s.cost_usd)}</td>
                <td className="num">{s.errors || ""}</td>
              </tr>
            ))}
            {!stages.length && (
              <tr>
                <td colSpan={8} className="muted">
                  No traces recorded for this briefing.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <h2>Editor rejections</h2>
      <Suspense fallback={<p className="muted">Loading rejections…</p>}>
        <BriefingRejections briefingId={b.id} />
      </Suspense>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card stat">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

function Script({
  lines,
  briefingId,
  selected,
}: {
  lines: LineSummary[];
  briefingId: string;
  selected?: string;
}) {
  return (
    <ol className="script">
      {lines.map((ln, i) => (
        <li key={ln.id}>
          {ln.story_title && ln.story_title !== lines[i - 1]?.story_title && (
            <div className="story">{ln.story_title}</div>
          )}
          <Link
            href={`/briefings/${briefingId}?line=${ln.id}`}
            scroll={false}
            aria-current={ln.id === selected ? "true" : undefined}
          >
            {ln.text}
            <VerdictDots verdicts={ln.verdicts} />
          </Link>
        </li>
      ))}
    </ol>
  );
}

async function Trace({ lineId }: { lineId: string }) {
  return <TracePanel trace={await api.trace(lineId)} />;
}

async function BriefingRejections({ briefingId }: { briefingId: string }) {
  const rows = await api.rejections({ briefing_id: briefingId, limit: 200 });
  return <RejectionTable rows={rows} showBriefing={false} />;
}
