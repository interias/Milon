export type NightStage = "deep" | "light" | "rem" | "awake" | "unknown";
export type NightMetric = "heart_rate" | "stress" | "body_battery" | "hrv";
export type NightPoint = { seconds: number; value: number };
export type NightSeries = {
  segments: NightPoint[][];
  samples: number;
  display_samples: number;
  minimum: number | null;
  maximum: number | null;
  gap_seconds: number;
};
export type GarminNightSummary = {
  day: string;
  started_at: string;
  ended_at: string;
  started_at_utc: string;
  ended_at_utc: string;
  window_minutes: number;
  asleep_minutes: number | null;
  awake_minutes: number | null;
  complete: boolean;
  stage_coverage: number;
  clock_change: boolean;
  synced_at: string | null;
  sync_issue: boolean;
};
export type GarminNightList = {
  source: "garmin_direct";
  timezone: string;
  from_date: string;
  to_date: string;
  nights: GarminNightSummary[];
  complete_nights: number;
};
export type GarminNight = GarminNightSummary & {
  source: "garmin_direct";
  timezone: string;
  phases: { start_seconds: number; end_seconds: number; stage: NightStage }[];
  stage_conflict: boolean;
  series: Record<NightMetric, NightSeries>;
  battery_change: number | null;
};

const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
async function get<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}/metrics/garmin/nights${path}`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Die Nachtansicht konnte nicht geladen werden.");
  return response.json();
}
export const garminNightsApi = {
  list: (days: 14 | 30, signal: AbortSignal) => get<GarminNightList>(`?days=${days}`, signal),
  night: (day: string, signal: AbortSignal) => get<GarminNight>(`/${day}`, signal),
};

export function nightClock(iso: string, zone: string) {
  return new Intl.DateTimeFormat("de-DE", { timeZone: zone, hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

/** Local-clock coordinates for cross-midnight rhythm rows, independent of browser timezone. */
export function nightWallHour(iso: string, wakingDay: string) {
  const [day, clock] = iso.split("T");
  const [hour, minute] = clock.split(":").map(Number);
  const dayDifference = (Date.parse(`${day}T12:00:00Z`) - Date.parse(`${wakingDay}T12:00:00Z`)) / 86_400_000;
  return dayDifference * 24 + hour + minute / 60;
}

export function nightValue(series: NightSeries, seconds: number): number | null {
  for (const segment of series.segments) {
    if (!segment.length || seconds < segment[0].seconds || seconds > segment[segment.length - 1].seconds) continue;
    return segment.reduce((best, point) => Math.abs(point.seconds - seconds) < Math.abs(best.seconds - seconds) ? point : best).value;
  }
  return null;
}
