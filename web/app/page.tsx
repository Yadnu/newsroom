import Link from "next/link";
import { Suspense } from "react";

import { VerdictCounts } from "@/components/Verdicts";
import { api } from "@/lib/api";
import { int, ms, shortId, usd, when } from "@/lib/format";

export default function Home() {
  return (
    <>
      <h1>Briefings</h1>
      <p className="sub">Open a briefing, then click any sentence to see its claims and sources.</p>
      <Suspense fallback={<p className="muted">Loading briefings…</p>}>
        <BriefingTable />
      </Suspense>
    </>
  );
}

async function BriefingTable() {
  const rows = await api.briefings(100);
  if (!rows.length) {
    return (
      <div className="card empty">
        No briefings yet. Run <code className="mono">newsroom brief --minutes 3</code>.
      </div>
    );
  }
  return (
    <div className="card table-wrap">
      <table>
        <thead>
          <tr>
            <th>Created</th>
            <th>Briefing</th>
            <th>Status</th>
            <th className="num">Target</th>
            <th className="num">Lines</th>
            <th>Claims</th>
            <th className="num">Wall time</th>
            <th className="num">Tokens</th>
            <th className="num">Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((b) => (
            <tr key={b.id}>
              <td>{when(b.created_at)}</td>
              <td>
                <Link href={`/briefings/${b.id}`} className="mono">
                  {shortId(b.id)}
                </Link>
              </td>
              <td>
                {b.status}
                {(b.status === "cleared" || b.status === "aired") && (
                  <>
                    {" · "}
                    <Link href={`/briefings/${b.id}/listen`}>listen</Link>
                  </>
                )}
              </td>
              <td className="num">{b.target_minutes} min</td>
              <td className="num">{b.lines}</td>
              <td>
                <VerdictCounts verdicts={b.verdicts} />
              </td>
              <td className="num">{ms(b.wall_ms)}</td>
              <td className="num">{int(b.tokens_in + b.tokens_out)}</td>
              <td className="num">{usd(b.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
