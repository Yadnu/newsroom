// The anchor: an original, flat-illustration character in layered SVG (head, eyes, lids, brows, mouth,
// torso), so each part moves on its own. All motion comes in as numbers from poseAt() and mouthAt();
// nothing here keeps time.

import type { Mouth } from "@/src/broadcast/lipsync";
import type { Pose } from "@/src/broadcast/pose";

const SKIN = "#c98e68";
const SKIN_SHADE = "#b37a57";
const HAIR = "#2b1d16";
const SUIT = "#1d2a45";
const SUIT_SHADE = "#16213a";
const SHIRT = "#f3f1ec";
const TIE = "#c62f3b";
const LIPS = "#8c4a44";
const MOUTH_IN = "#4a1d20";

/** Mouth as an ellipse plus optional teeth, centred on (0, 0). */
function MouthShape({ mouth }: { mouth: Mouth }) {
  const o = mouth.open;
  switch (mouth.shape) {
    case "rest":
      return <path d="M -15 0 Q 0 4 15 0" stroke={LIPS} strokeWidth={3} fill="none" strokeLinecap="round" />;
    case "closed":
      return <path d="M -14 0 Q 0 2 14 0" stroke={LIPS} strokeWidth={4.5} fill="none" strokeLinecap="round" />;
    case "fv":
      return (
        <g>
          <ellipse cx={0} cy={1} rx={13} ry={3 + 3 * o} fill={MOUTH_IN} />
          <rect x={-9} y={-2} width={18} height={3} rx={1} fill="#fff" />
          <path d="M -13 2 Q 0 6 13 2" stroke={LIPS} strokeWidth={3} fill="none" strokeLinecap="round" />
        </g>
      );
    default: {
      const size: Record<string, [number, number]> = {
        ah: [14, 3 + 13 * o],
        ee: [17, 2 + 7 * o],
        oh: [10, 4 + 11 * o],
        oo: [7, 4 + 7 * o],
      };
      const [rx, ry] = size[mouth.shape] ?? [12, 3 + 8 * o];
      return (
        <g>
          <ellipse cx={0} cy={ry * 0.35} rx={rx} ry={ry} fill={MOUTH_IN} stroke={LIPS} strokeWidth={2.5} />
          {mouth.shape !== "oo" && ry > 5 && (
            <rect x={-rx * 0.6} y={ry * 0.35 - ry + 1} width={rx * 1.2} height={Math.min(4, ry * 0.4)} rx={1} fill="#fff" />
          )}
        </g>
      );
    }
  }
}

function Eye({ cx, pose }: { cx: number; pose: Pose }) {
  const lid = Math.max(pose.blink, 0.45 * pose.lookDown); // lids lower toward the papers
  const lookY = 3 * pose.lookDown;
  return (
    <g>
      <ellipse cx={cx} cy={0} rx={11} ry={7} fill="#fff" />
      <circle cx={cx} cy={lookY} r={5} fill="#3b2a20" />
      <circle cx={cx + 1.5} cy={lookY - 1.5} r={1.4} fill="#fff" />
      {/* Upper lid: a skin-coloured cap that slides down over the eye. */}
      <rect x={cx - 12} y={-8} width={24} height={16 * lid + 0.01} fill={SKIN} />
      <path d={`M ${cx - 12} ${-8 + 16 * lid} Q ${cx} ${-10 + 16 * lid} ${cx + 12} ${-8 + 16 * lid}`} stroke="#3b2a20" strokeWidth={1.6} fill="none" />
    </g>
  );
}

export function Anchor({ pose, mouth }: { pose: Pose; mouth: Mouth }) {
  const pitchY = pose.headPitch * 0.7; // looking down: the head drops a little
  const featuresY = pose.headPitch * 0.35; // and the face turns toward the desk
  return (
    <svg viewBox="0 0 400 520" role="img" aria-label="The news anchor" className="h-full w-full overflow-visible">
      {/* Torso: breathes. */}
      <g transform={`translate(0 ${-pose.breath})`}>
        <path d="M 40 520 C 50 380 110 330 200 322 C 290 330 350 380 360 520 Z" fill={SUIT} />
        <path d="M 200 322 L 160 330 L 200 440 L 240 330 Z" fill={SHIRT} />
        <path d="M 193 338 L 207 338 L 213 352 L 205 440 L 200 448 L 195 440 L 187 352 Z" fill={TIE} />
        <path d="M 160 330 L 200 440 L 175 470 L 120 360 Z" fill={SUIT_SHADE} />
        <path d="M 240 330 L 200 440 L 225 470 L 280 360 Z" fill={SUIT_SHADE} />
        <rect x={180} y={286} width={40} height={44} rx={10} fill={SKIN_SHADE} />
      </g>

      {/* Head: tilts, looks down, nods. */}
      <g transform={`translate(0 ${pitchY - pose.breath * 0.6}) rotate(${pose.headTilt} 200 300)`}>
        <ellipse cx={128} cy={205} rx={12} ry={20} fill={SKIN_SHADE} />
        <ellipse cx={272} cy={205} rx={12} ry={20} fill={SKIN_SHADE} />
        <path d="M 130 170 C 130 100 270 100 270 170 L 268 230 C 262 285 230 305 200 305 C 170 305 138 285 132 230 Z" fill={SKIN} />
        <path d="M 124 185 C 112 95 180 70 214 78 C 262 86 290 120 276 186 C 270 150 250 128 214 124 C 180 122 150 132 136 160 Z" fill={HAIR} />

        <g transform={`translate(0 ${featuresY})`}>
          <g transform={`translate(0 ${-5 * pose.brow})`}>
            <path d="M 152 168 Q 167 160 182 166" stroke={HAIR} strokeWidth={5} fill="none" strokeLinecap="round" />
            <path d="M 218 166 Q 233 160 248 168" stroke={HAIR} strokeWidth={5} fill="none" strokeLinecap="round" />
          </g>
          <g transform="translate(0 190)">
            <Eye cx={167} pose={pose} />
            <Eye cx={233} pose={pose} />
          </g>
          <path d="M 200 196 L 192 236 Q 200 242 209 236" stroke={SKIN_SHADE} strokeWidth={3} fill="none" strokeLinecap="round" />
          <g transform="translate(200 262)">
            <MouthShape mouth={mouth} />
          </g>
        </g>
      </g>
    </svg>
  );
}
