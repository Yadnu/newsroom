import type { ClaimTrace } from "@/lib/api";
import { when } from "@/lib/format";

import { SourceLink } from "./SourceLink";
import { Badge } from "./Verdicts";

export function TracePanel({ trace }: { trace: ClaimTrace }) {
  const replaced = trace.history.filter((j) => !j.current);
  return (
    <section className="card trace" aria-label="Claim trace">
      <h2 style={{ marginTop: 0 }}>Sentence {trace.order + 1}</h2>
      <blockquote>{trace.text}</blockquote>
      {trace.story_title && <p className="muted">Story: {trace.story_title}</p>}

      {trace.claims.length === 0 && (
        <p className="muted">No factual claims on this line (a transition or sign-off).</p>
      )}

      {trace.claims.map((c) => (
        <div className="claim" key={c.id}>
          <p>
            <Badge verdict={c.verdict} />
            {c.score != null && <span className="muted mono">score {c.score.toFixed(2)}</span>}
            {c.rewrite_round > 0 && (
              <span className="muted"> · after rewrite round {c.rewrite_round}</span>
            )}
          </p>
          <p>{c.text}</p>
          {c.reason && <p className="muted">{c.reason}</p>}

          <strong>Sources</strong>
          {c.cited.length ? (
            <ul className="sources">
              {c.cited.map((s) => (
                <li key={s.id}>
                  <SourceLink source={s} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No cited sources.</p>
          )}

          {c.evidence.length > 0 && (
            <details open={c.verdict !== "approved"}>
              <summary>Evidence the Editor used ({c.evidence.length})</summary>
              {c.evidence.map((e, i) => (
                <div key={`${e.source.id}-${i}`}>
                  <div className="passage">{e.passage}</div>
                  <small>
                    <SourceLink source={e.source} />
                    {e.score != null && <span className="muted mono"> · {e.score.toFixed(2)}</span>}
                  </small>
                </div>
              ))}
            </details>
          )}
        </div>
      ))}

      {replaced.length > 0 && (
        <div className="claim">
          <strong>Earlier verdicts</strong>
          <p className="muted">Claims the Editor sent back before this wording was approved.</p>
          {replaced.map((j) => (
            <div key={j.trace_id} style={{ margin: "8px 0" }}>
              <Badge verdict={j.verdict} /> <span className="muted">{when(j.at)}</span>
              <p>{j.claim}</p>
              {j.reason && <p className="muted">{j.reason}</p>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
