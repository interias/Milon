export type ReferenceRun = { activity_id: string; title: string; started_at: string; distance_km: number | null };
export type ReferenceSelection = { reference: ReferenceRun | null; selectable: boolean | null; reason: string | null };
export type ReferenceObservation = ReferenceRun & { matched_pairs: number; hr_delta_bpm: number; pace_delta_seconds: number; first_hr: number; second_hr: number };
export type RunReference = {
  status: "unset" | "ready" | "unavailable";
  reference: ReferenceRun | null;
  observations: ReferenceObservation[];
  days: number;
  period_start: string;
  period_end: string;
  sensor_since: string | null;
  sensor_label: string | null;
  reason: string | null;
  method: string;
};

const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
async function request<T>(path: string, signal?: AbortSignal, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`${BASE}/running/reference${path}`, {
    signal, method, cache: "no-store", ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    const result = await response.json().catch(() => null);
    throw new Error(typeof result?.detail === "string" ? result.detail : "Referenzrunde konnte nicht geladen werden.");
  }
  return response.json() as Promise<T>;
}
export const runReferenceApi = {
  overview: (days: number, signal: AbortSignal) => request<RunReference>(`?days=${days}`, signal),
  selection: (activityId: string, signal: AbortSignal) => request<ReferenceSelection>(`/selection?activity_id=${encodeURIComponent(activityId)}`, signal),
  choose: (activityId: string) => request<ReferenceSelection>("", undefined, "PUT", { activity_id: activityId }),
  clear: () => request<ReferenceSelection>("", undefined, "DELETE"),
};
