export type AtlasMember = {
  activity_id: string; title: string; started_at: string; distance_km: number | null;
  pace_seconds: number | null; avg_hr: number | null;
};
type AtlasChange = { first: number; last: number; delta: number; from: string; to: string; n: number };
export type RouteFamily = {
  anchor_id: string; contour: [number, number][][]; count: number;
  latest: AtlasMember; members: AtlasMember[];
  changes: { pace_seconds: AtlasChange | null; avg_hr: AtlasChange | null }; sensor_label: string;
};
export type RouteAtlasData = {
  groups: RouteFamily[]; total_runs: number; threshold_pct: number; tolerance_m: number; method: string;
  configured?: boolean; sync?: { last_sync: string | null; status: string | null } | null;
};
const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
export async function loadRouteAtlas(signal: AbortSignal): Promise<RouteAtlasData> {
  const response = await fetch(`${BASE}/metrics/running/route-atlas`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Der Streckenatlas konnte nicht geladen werden (${response.status}).`);
  return response.json();
}
