export type MechanicsMetric = {
  key: string; label: string; unit: string; definition: string;
  status: "observed" | "collecting" | "excluded";
  pairs: number; known_minutes: number; early: number | null; late: number | null;
  delta: number | null; delta_min: number | null; delta_max: number | null;
  pace_delta_seconds: number | null; series: { minute: number; value: number }[];
};
export type RunMechanicsData = {
  activity_id: string; source: string; status: string; eligible_minutes: number;
  midpoint_minute: number; reason: string; method: string; metrics: MechanicsMetric[];
  impact_load_km: number | null;
};
export type RunningLoadWeek = {
  week: string; runs: number; paired_runs: number; distance_km: number | null;
  impact_load_km: number | null; all_distance_km: number | null;
  leg_days: string[]; excluded_runs: number; provisional: boolean;
  activities: { activity_id: string; date: string; distance_km: number | null; impact_load_km: number | null }[];
};
export type RunningLoadData = {
  source: string; weeks: RunningLoadWeek[]; method: string;
  tolerance: { available: boolean; status: string; stale: boolean; fetched_at: string | null;
    date: string | null; tolerance_km: number | null; acute_load_km: number | null; reason: string };
};
const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
async function request<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}/metrics/running/mechanics${path}`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Laufdaten konnten nicht geladen werden (${response.status}).`);
  return response.json() as Promise<T>;
}
export const mechanicsApi = {
  activity: (id: string, signal: AbortSignal) => request<RunMechanicsData>(`/${encodeURIComponent(id)}`, signal),
  load: (weeks: number, signal: AbortSignal) => request<RunningLoadData>(`/load?weeks=${weeks}`, signal),
};
