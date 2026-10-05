export type GarminActivityPoint = {
  elapsed_seconds: number;
  distance_m: number | null;
  hr_bpm: number | null;
  speed_m_s: number | null;
  altitude_m: number | null;
  cadence_spm: number | null;
  power_w: number | null;
  gap: boolean;
};

export type GarminActivity = {
  activity_id: string;
  available: boolean;
  canonical_external_id: string | null;
  summary: {
    title: string;
    started_at: string;
    started_at_utc?: string | null;
    distance_km: number | null;
    duration_seconds: number | null;
    elapsed_seconds: number | null;
    avg_hr: number | null;
    max_hr: number | null;
    elevation_gain_m: number | null;
    avg_cadence_spm: number | null;
    avg_power_w: number | null;
    ground_contact_ms: number | null;
    stride_length_cm: number | null;
    vertical_oscillation_cm: number | null;
    vertical_ratio_pct: number | null;
    training_effect: number | null;
    anaerobic_training_effect: number | null;
  };
  quality: {
    complete: boolean;
    canonical: boolean;
    points: number;
    reported_points: number | null;
    hr_coverage: number;
    speed_coverage: number;
    reason: string | null;
    last_issue?: string | null;
    source: "garmin_direct";
  };
  series: GarminActivityPoint[];
  laps: {
    index: number;
    distance_m: number | null;
    duration_seconds: number | null;
    elapsed_seconds: number | null;
    avg_hr: number | null;
    max_hr: number | null;
    avg_cadence_spm: number | null;
    avg_power_w: number | null;
    elevation_gain_m: number | null;
  }[];
  zone_source: "garmin_recorded";
  zones: { zone: number; hr_low: number; hr_high: number | null; seconds: number }[];
  synced_at?: string | null;
};

export type GarminRecoveryMetric = {
  value: number;
  date: string;
  measured_at: string | null;
  synced_at: string;
  provisional: boolean;
  stale: boolean;
  baseline_low_ms?: number | null;
  baseline_high_ms?: number | null;
  baseline_ready?: boolean;
  status?: string | null;
};
export type GarminRecoveryPoint = {
  date: string;
  provisional: boolean;
  hrv_ms: number | null;
  rhr_bpm: number | null;
  readiness: number | null;
  readiness_at: string | null;
  recovery_hours: number | null;
  body_battery: number | null;
  stress: number | null;
  sleep_hours: number | null;
  sleep_score: number | null;
  baseline_low_ms: number | null;
  baseline_high_ms: number | null;
  hrv_status: string | null;
};
export type GarminRecovery = {
  source: "garmin_direct";
  updated_at: string | null;
  stale: boolean;
  series: GarminRecoveryPoint[];
  latest: Record<"hrv_ms" | "rhr_bpm" | "readiness" | "recovery_hours" | "body_battery" | "stress" | "sleep_hours" | "sleep_score", GarminRecoveryMetric | null>;
  coverage: { days: number; hrv_nights: number; resting_hr_days: number; sleep_nights: number };
  availability: Record<"summary" | "sleep" | "hrv" | "vo2" | "readiness", { status: "available" | "empty" | "error" | "unsupported" | "never"; attempted_at: string | null; last_success_at: string | null }>;
  notes: string[];
};

const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
async function request<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Garmin-Daten konnten nicht geladen werden (${response.status}).`);
  return response.json() as Promise<T>;
}
export const garminApi = {
  activity: (id: string, signal: AbortSignal) => request<GarminActivity>(`/metrics/running/activities/${encodeURIComponent(id)}`, signal),
  recovery: (signal: AbortSignal) => request<GarminRecovery>("/metrics/garmin/recovery?days=30", signal),
};

export const finite = (value: number | null | undefined): value is number => value != null && Number.isFinite(value);
export const paceSeconds = (speed: number | null) => finite(speed) && speed > 0 ? 1000 / speed : null;
export function paceLabel(seconds: number | null) {
  if (!finite(seconds)) return "–";
  const rounded = Math.round(seconds);
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}`;
}

export function activitySegments(points: GarminActivityPoint[], value: (point: GarminActivityPoint) => number | null) {
  const segments: { time: number; value: number }[][] = [];
  let current: { time: number; value: number }[] = [];
  for (const point of points) {
    const number = value(point);
    if (point.gap || !finite(number)) {
      if (current.length) segments.push(current);
      current = [];
    }
    if (finite(number)) current.push({ time: point.elapsed_seconds, value: number });
  }
  if (current.length) segments.push(current);
  return segments;
}

export function nearestActivityPoint(points: GarminActivityPoint[], time: number) {
  if (!points.length) return null;
  let low = 0, high = points.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (points[middle].elapsed_seconds < time) low = middle + 1; else high = middle;
  }
  return low > 0 && time - points[low - 1].elapsed_seconds < points[low].elapsed_seconds - time ? low - 1 : low;
}
