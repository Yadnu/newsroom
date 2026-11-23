// The studio set (task 8.4): skyline backdrop with a slow light sweep, the anchor, and the desk. Drawn
// in one 16:9 SVG; every moving part is a function of show time (`time`), so pause and seek hold.

import type { Mouth } from "@/src/broadcast/lipsync";
import type { Pose } from "@/src/broadcast/pose";

import { Anchor } from "./Anchor";

const W = 1600;
const H = 900;

/** A fixed skyline: [x, width, height] per building. */
const BUILDINGS: ReadonlyArray<readonly [number, number, number]> = [
  [0, 90, 300], [80, 70, 380], [150, 110, 260], [255, 60, 420], [310, 120, 330], [425, 80, 470],
  [500, 140, 300], [635, 70, 390], [700, 120, 250], [815, 90, 440], [900, 130, 320], [1025, 70, 500],
  [1090, 110, 280], [1195, 90, 410], [1280, 120, 340], [1395, 70, 460], [1460, 140, 300],
];

function windowLit(i: number, j: number): boolean {
  const x = Math.sin(i * 91.7 + j * 37.3) * 1000;
  return x - Math.floor(x) > 0.62;
}

export function StudioScene({
  time,
  pose,
  mouth,
  reducedMotion,
}: {
  time: number;
  pose: Pose;
  mouth: Mouth;
  reducedMotion: boolean;
}) {
  const sweep = reducedMotion ? 400 : ((time / 18) % (W + 800)) - 400; // light drifts across the set
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid slice" className="absolute inset-0 h-full w-full" aria-hidden>
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#0a1426" />
          <stop offset="0.65" stopColor="#13284a" />
          <stop offset="1" stopColor="#1c3561" />
        </linearGradient>
        <radialGradient id="sweep" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#6aa0ff" stopOpacity="0.22" />
          <stop offset="1" stopColor="#6aa0ff" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="desk" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#24324f" />
          <stop offset="1" stopColor="#0e1628" />
        </linearGradient>
        <linearGradient id="deskTop" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#3a4a6e" />
          <stop offset="0.5" stopColor="#56688f" />
          <stop offset="1" stopColor="#3a4a6e" />
        </linearGradient>
      </defs>

      {/* Backdrop: skyline behind glass. */}
      <rect width={W} height={H} fill="url(#sky)" />
      <g opacity={0.55}>
        {BUILDINGS.map(([x, w, h], i) => (
          <g key={i}>
            <rect x={x} y={640 - h} width={w} height={h + 260} fill="#0b1830" />
            {Array.from({ length: Math.floor(h / 34) }, (_, j) =>
              Array.from({ length: Math.floor(w / 26) }, (_, k) =>
                windowLit(i * 7 + k, j) ? (
                  <rect key={`${j}-${k}`} x={x + 8 + k * 26} y={640 - h + 14 + j * 34} width={10} height={14} fill="#f2c46b" opacity={0.7} />
                ) : null,
              ),
            )}
          </g>
        ))}
      </g>
      <ellipse cx={sweep} cy={330} rx={420} ry={300} fill="url(#sweep)" />
      {/* Window frame of the set. */}
      <g stroke="#1f3358" strokeWidth={10} opacity={0.9}>
        <line x1={0} y1={120} x2={W} y2={120} />
        <line x1={400} y1={120} x2={400} y2={700} />
        <line x1={800} y1={120} x2={800} y2={700} />
        <line x1={1200} y1={120} x2={1200} y2={700} />
      </g>

      {/* The anchor, seated behind the desk. */}
      <svg x={110} y={40} width={640} height={832} viewBox="0 0 400 520" overflow="visible">
        <Anchor pose={pose} mouth={mouth} />
      </svg>

      {/* Desk, papers, branding. */}
      <path d={`M 0 700 L ${W} 700 L ${W} ${H} L 0 ${H} Z`} fill="url(#desk)" />
      <rect x={0} y={690} width={W} height={18} fill="url(#deskTop)" />
      <g transform={`translate(340 ${676 - 6 * (1 - pose.lookDown)})`}>
        <rect x={0} y={0} width={150} height={18} rx={2} fill="#f5f3ee" transform="rotate(-3)" />
        <rect x={20} y={-4} width={150} height={18} rx={2} fill="#e9e6df" transform="rotate(2)" />
      </g>
      <rect x={0} y={760} width={W} height={6} fill="#d7263d" />
      <text x={W / 2} y={850} textAnchor="middle" fontFamily="var(--font-oswald), sans-serif" fontSize={64} letterSpacing={18} fill="#e8edf7" opacity={0.92}>
        NEWSROOM
      </text>
    </svg>
  );
}
