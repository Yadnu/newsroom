import Link from "next/link";

import type { Rejection } from "@/lib/api";
import { shortId, when } from "@/lib/format";

import { Badge } from "./Verdicts";

export function RejectionTable({
  rows,
  showBriefing = true,
}: {
  rows: Rejection[];
  showBriefing?: boolean;
}) {
  if (!rows.length) return <div className="card empty">The Editor sent nothing back.</div>;
  return (
    <div className="card table-wrap">
      <table>
        <thead>
          <tr>
            <th>When</th>
            <th>Verdict</th>
            <th>Claim</th>
            <th>Reason</th>
            <th>Sentence</th>
            {showBriefing && <th>Briefing</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.trace_id}>
              <td>{when(r.at)}</td>
              <td>
                <Badge verdict={r.verdict} />
                {!r.current && <span className="muted"> replaced</span>}
              </td>
              <td className="wrap">{r.claim}</td>
              <td className="wrap muted">{r.reason}</td>
              <td className="wrap">
                {r.line_id && r.briefing_id ? (
                  <Link href={`/briefings/${r.briefing_id}?line=${r.line_id}`}>
                    {r.line_text ?? "open sentence"}
                  </Link>
                ) : (
                  <span className="muted">not linked (judged before task 3.1)</span>
                )}
              </td>
              {showBriefing && (
                <td>
                  {r.briefing_id ? (
                    <Link href={`/briefings/${r.briefing_id}`} className="mono">
                      {shortId(r.briefing_id)}
                    </Link>
                  ) : (
                    "–"
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
