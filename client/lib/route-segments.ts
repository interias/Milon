import type { CohortRun, RunDistribution } from "./run-insights";

export type SectionValue = { pace_seconds: number; avg_hr: number | null; hr_coverage_pct: number; distance_m: number };
export type RouteSection = {
  index: number; start_m: number; end_m: number; contour: number[][];
  selected: SectionValue | null; n: number; omitted_runs: number;
  runs: (SectionValue & { activity_id: string; started_at: string })[];
  metrics: { pace_seconds: RunDistribution; avg_hr: RunDistribution };
};
export type RouteSegmentsData = {
  activity_id: string; status: "ready" | "unavailable"; reason: string | null;
  selected: CohortRun; cohort_runs: number; section_m: number;
  contour: number[][]; sections: RouteSection[]; method: string;
};
const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
export async function routeSegments(id: string, signal: AbortSignal): Promise<RouteSegmentsData> {
  const response = await fetch(`${BASE}/metrics/running/segments/${encodeURIComponent(id)}`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Der Abschnittsvergleich konnte nicht geladen werden (${response.status}).`);
  return response.json();
}
