// Browser client for the FastAPI backend, through this app's /api rewrite (same origin).
import type { components } from "@/lib/api-types";

type S = components["schemas"];
export type PressStory = S["PressStory"];
export type PressSource = S["PressSource"];
export type PressPage = S["PressPage"];
export type PressCursor = S["PressCursor"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
  ) {
    super(status === 0 ? `The newsroom API is unreachable (${path})` : `API ${status} for ${path}`);
  }
}

type Query = Record<string, string | number | undefined>;

export function apiUrl(path: string, query: Query = {}): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined) params.set(k, String(v));
  const qs = params.toString();
  return `/api${path}${qs ? `?${qs}` : ""}`;
}

export async function apiGet<T>(
  path: string,
  query: Query = {},
  fetcher: typeof fetch = fetch,
): Promise<T> {
  let res: Response;
  try {
    res = await fetcher(apiUrl(path, query), { headers: { accept: "application/json" } });
  } catch {
    throw new ApiError(0, path);
  }
  // The Next rewrite answers 500/502/504 when the backend is down.
  if (!res.ok) throw new ApiError(res.status, path);
  return (await res.json()) as T;
}

export const PAGE_SIZE = 10;

export function pressPage(after: PressCursor | null, fetcher?: typeof fetch): Promise<PressPage> {
  return apiGet<PressPage>(
    "/press/stories",
    {
      limit: PAGE_SIZE,
      after_latest_at: after?.latest_at,
      after_id: after?.id,
    },
    fetcher,
  );
}
