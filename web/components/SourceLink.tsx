import type { SourceRef } from "@/lib/api";
import { safeHref } from "@/lib/format";

export function SourceLink({ source }: { source: SourceRef }) {
  const href = safeHref(source.url);
  const label = (
    <>
      <b>{source.outlet}</b>: {source.title}
    </>
  );
  return (
    <>
      {href ? (
        <a href={href} target="_blank" rel="noopener noreferrer nofollow">
          {label}
        </a>
      ) : (
        <span>{label}</span>
      )}
      {source.retracted && <span className="badge rejected">retracted</span>}
    </>
  );
}
