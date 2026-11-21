// Server-only client for the FastAPI backend. Types come from openapi.json (npm run gen:api).
import "server-only";

import { notFound } from "next/navigation";
import { connection } from "next/server";

import type { components } from "./api-types";
import { wsBase } from "./player";

type S = components["schemas"];
export type BriefingSummary = S["BriefingSummary"];
export type BriefingDetail = S["BriefingDetail"];
export type LineSummary = S["LineSummary"];
export type Stage = S["Stage"];
export type ClaimTrace = S["ClaimTrace"];
export type TracedClaim = S["TracedClaim"];
export type SourceRef = S["SourceRef"];
export type Judgement = S["Judgement"];
export type Rejection = S["Rejection"];
export type CorrectionRef = S["CorrectionRef"];

const API_URL = (process.env.NEWSROOM_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** WebSocket base the *browser* uses for the live Anchor stream (the API as the listener sees it). */
export function publicWsUrl(): string {
  return wsBase(process.env.NEWSROOM_PUBLIC_API_URL ?? API_URL);
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
  ) {
    super(`API ${status} for ${path}`);
  }
}

type Query = Record<string, string | number | boolean | undefined>;

async function get<T>(path: string, query: Query = {}): Promise<T> {
  await connection(); // always request-time: the archive changes with every briefing
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined) params.set(k, String(v));
  const qs = params.size ? `?${params}` : "";
  const res = await fetch(`${API_URL}${path}${qs}`, { cache: "no-store" });
  if (res.status === 404) notFound();
  if (!res.ok) throw new ApiError(res.status, path);
  return (await res.json()) as T;
}

const id = (value: string) => encodeURIComponent(value);

export const api = {
  briefings: (limit = 50) => get<BriefingSummary[]>("/archive/briefings", { limit }),
  briefing: (briefingId: string) => get<BriefingDetail>(`/archive/briefings/${id(briefingId)}`),
  trace: (lineId: string) => get<ClaimTrace>(`/archive/lines/${id(lineId)}/trace`),
  rejections: (q: { briefing_id?: string; limit?: number; include_rewrite?: boolean } = {}) =>
    get<Rejection[]>("/archive/rejections", q),
};
