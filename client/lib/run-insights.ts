import type { RunRoutePoint, ProjectedRoutePoint } from "./run-routes";

export type ZoneSummary = {
  source: "milon_hrmax";
  label: string;
  hr_max: number | null;
  zones: { zone: number; label: string; hr_low: number; hr_high: number; seconds: number }[];
  known_seconds: number;
  unknown_seconds: number;
  outside_seconds: number;
  total_seconds: number;
  method: string;
};
export type RunInsightCandidate = { activity_id: string; title: string; started_at: string; distance_km: number | null; similarity_label: string; similar_route: boolean };
export type RunInsights = {
  activity_id: string;
  available: boolean;
  drift: { status: "observed" | "insufficient" | "excluded"; value_pct: number | null; hr_delta_bpm: number | null; matched_pairs: number; paired_minutes: number; early_hr: number | null; late_hr: number | null; reason: string; method: string };
  zones: ZoneSummary;
  candidates: RunInsightCandidate[];
};
export type WeeklyRunZones = { source: string; label: string; hr_max: number | null; weeks: (ZoneSummary & { week: string; runs: number; excluded_runs: number })[]; method: string };
export type ComparisonPoint = { distance_m: number; hr_bpm: number | null; pace_seconds: number | null; gap: boolean };
export type ComparedRun = { activity_id: string; title: string; started_at: string; distance_km: number | null; series: ComparisonPoint[] };
export type RunComparisonData = {
  first: ComparedRun;
  second: ComparedRun;
  comparison: { status: "observed" | "insufficient" | "excluded"; matched_pairs: number; hr_delta_bpm: number | null; pace_delta_seconds: number | null; first_hr: number | null; second_hr: number | null; reason: string; method: string; similar_route: boolean };
};

export type CohortRun = {
  activity_id: string;
  title: string;
  started_at: string;
  distance_km: number | null;
  pace_seconds: number | null;
  avg_hr: number | null;
};
export type RunDistribution = {
  n: number;
  selected: number | null;
  median: number | null;
  min: number | null;
  max: number | null;
  q1: number | null;
  q3: number | null;
  delta: number | null;
};
export type RunCohortComparison = {
  activity_id: string;
  status: "ready" | "empty" | "unavailable";
  reason: string | null;
  selected: CohortRun;
  cohort: (CohortRun & { overlap_pct: number })[];
  threshold_pct: number;
  tolerance_m: number;
  sensor_since: string | null;
  sensor_label: string;
  period_start: string | null;
  period_end: string | null;
  metrics: { pace_seconds: RunDistribution; avg_hr: RunDistribution };
  method: string;
};

const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
async function request<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}/metrics/running/insights${path}`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Die Laufanalyse konnte nicht geladen werden (${response.status}).`);
  return response.json() as Promise<T>;
}
export const runInsightsApi = {
  activity: (id: string, signal: AbortSignal) => request<RunInsights>(`/${encodeURIComponent(id)}`, signal),
  zones: (signal: AbortSignal) => request<WeeklyRunZones>("/zones?weeks=8", signal),
  compare: (first: string, second: string, signal: AbortSignal) => request<RunComparisonData>(`/compare?first=${encodeURIComponent(first)}&second=${encodeURIComponent(second)}`, signal),
  cohort: (id: string, signal: AbortSignal) => request<RunCohortComparison>(`/cohort/${encodeURIComponent(id)}`, signal),
};

export function comparisonSegments(points: ComparisonPoint[], value: (point: ComparisonPoint) => number | null) {
  const segments: { distance: number; value: number }[][] = [];
  let current: { distance: number; value: number }[] = [];
  let previousDistance: number | null = null;
  for (const point of points) {
    const number = value(point);
    const valid = Number.isFinite(point.distance_m) && number != null && Number.isFinite(number);
    if (point.gap || !valid || (previousDistance != null && point.distance_m <= previousDistance)) {
      if (current.length) segments.push(current);
      current = [];
    }
    if (valid) current.push({ distance: point.distance_m, value: number! });
    previousDistance = point.distance_m;
  }
  if (current.length) segments.push(current);
  return segments;
}

type TimedRoutePoint = ProjectedRoutePoint & { elapsed: number };

function utcMillis(value: string | null | undefined): number | null {
  if (!value || !/(Z|[+-]\d{2}:\d{2})$/i.test(value)) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

// Preserve segment boundaries and missing timestamps; never infer a local timezone.
export function timedRoute(segments: RunRoutePoint[][], projected: ProjectedRoutePoint[][], startedAtUtc: string | null | undefined): TimedRoutePoint[][] {
  const start = utcMillis(startedAtUtc);
  if (start == null) return [];
  const result: TimedRoutePoint[][] = [];
  segments.forEach((segment, segmentIndex) => {
    let current: TimedRoutePoint[] = [];
    segment.forEach((point, pointIndex) => {
      const time = utcMillis(point.time), position = projected[segmentIndex]?.[pointIndex];
      const elapsed = time == null ? null : (time - start) / 1000;
      const previous = current.at(-1);
      if (elapsed == null || !position || (previous && (elapsed <= previous.elapsed || elapsed - previous.elapsed > 30))) {
        if (current.length) result.push(current);
        current = [];
      }
      if (elapsed != null && position) current.push({ ...position, elapsed });
    });
    if (current.length) result.push(current);
  });
  return result;
}

export function routePosition(segments: TimedRoutePoint[][], elapsed: number | null): ProjectedRoutePoint | null {
  if (elapsed == null || !Number.isFinite(elapsed)) return null;
  for (const segment of segments) {
    if (elapsed < segment[0].elapsed || elapsed > segment.at(-1)!.elapsed) continue;
    for (let index = 0; index < segment.length; index++) {
      const point = segment[index];
      if (point.elapsed === elapsed) return { x: point.x, y: point.y };
      if (point.elapsed > elapsed && index > 0) {
        const previous = segment[index - 1];
        const fraction = (elapsed - previous.elapsed) / (point.elapsed - previous.elapsed);
        return { x: previous.x + (point.x - previous.x) * fraction, y: previous.y + (point.y - previous.y) * fraction };
      }
    }
  }
  return null;
}
