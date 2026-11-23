// Card visuals and labels that depend only on data.

const PALETTES: ReadonlyArray<readonly [string, string]> = [
  ["#1b2a4a", "#3d5a99"],
  ["#2a1b3d", "#7a3d8c"],
  ["#10302a", "#1f7a66"],
  ["#3a1f14", "#b4441e"],
  ["#15232f", "#2f6f8f"],
  ["#2b2b12", "#8a7a1f"],
];

/** A stable gradient for a story without an image (same story, same colors). */
export function gradientFor(id: string): string {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const [a, b] = PALETTES[h % PALETTES.length];
  const angle = 120 + (h % 90);
  return `linear-gradient(${angle}deg, ${a} 0%, ${b} 100%)`;
}

/** "just now", "12 min ago", "3 h ago", "2 days ago", then a date. */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const s = Math.round((now.getTime() - then.getTime()) / 1000);
  if (Number.isNaN(s)) return "";
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 7 * 86_400) {
    const d = Math.floor(s / 86_400);
    return `${d} day${d === 1 ? "" : "s"} ago`;
  }
  return then.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

export function outletsLine(outlets: readonly string[], max = 3): string {
  if (outlets.length <= max) return outlets.join(" · ");
  return `${outlets.slice(0, max).join(" · ")} +${outlets.length - max}`;
}
