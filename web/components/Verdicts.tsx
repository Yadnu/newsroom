import { verdictCounts } from "@/lib/format";

export function Badge({ verdict, children }: { verdict: string; children?: React.ReactNode }) {
  return <span className={`badge ${verdict}`}>{children ?? verdict}</span>;
}

export function VerdictCounts({ verdicts }: { verdicts: Record<string, number> }) {
  const counts = verdictCounts(verdicts);
  if (!counts.length) return <span className="muted">no claims</span>;
  return (
    <>
      {counts.map(([v, n]) => (
        <Badge key={v} verdict={v}>
          {n} {v}
        </Badge>
      ))}
    </>
  );
}

export function VerdictDots({ verdicts }: { verdicts: Record<string, number> }) {
  const counts = verdictCounts(verdicts);
  return (
    <span className="dots" aria-label={counts.map(([v, n]) => `${n} ${v}`).join(", ")}>
      {counts.flatMap(([v, n]) =>
        Array.from({ length: n }, (_, i) => <span key={`${v}${i}`} className={`dot ${v}`} />),
      )}
    </span>
  );
}
