// Pure display helpers.

export const VERDICTS = ["approved", "rewrite", "rejected", "pending"] as const;

export function ms(value: number | null | undefined): string {
  if (value == null) return "–";
  if (value < 1000) return `${Math.round(value)} ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(1)} s`;
  const m = Math.floor(value / 60_000);
  return `${m}m ${Math.round((value % 60_000) / 1000)}s`;
}

export function usd(value: number | null | undefined): string {
  if (value == null) return "–";
  if (value === 0) return "$0";
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

export function int(value: number | null | undefined): string {
  return value == null ? "–" : value.toLocaleString("en-US");
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) +
        " UTC";
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

/** Source URLs come from fetched feeds: only ever link http(s). */
export function safeHref(url: string): string | undefined {
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : undefined;
  } catch {
    return undefined;
  }
}

export function verdictCounts(verdicts: Record<string, number>): [string, number][] {
  const known = VERDICTS.filter((v) => verdicts[v]).map((v) => [v, verdicts[v]] as [string, number]);
  const other = Object.entries(verdicts).filter(
    ([v, n]) => n && !(VERDICTS as readonly string[]).includes(v),
  );
  return [...known, ...other];
}
