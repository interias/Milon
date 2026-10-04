export type MeasureKey =
  | "abdomen_navel" | "waist_narrowest" | "hip_widest" | "upper_arm_right"
  | "chest_nipple" | "shoulders_deltoid" | "thigh_right_mid" | "calf_right_max";
export type CircumferencePeriod = "1m" | "3m" | "6m" | "12m" | "all";
export type CircumferenceDefinition = {
  key: MeasureKey; name: string; site: string; color: string; definition: string;
  guide: [number, number, number, number];
};
export type CircumferenceInput = {
  date: string; protocol: "standard" | "unknown";
  values: Partial<Record<MeasureKey, number>>;
};
export type CircumferenceEntry = CircumferenceInput & { id: number };
export type CircumferencePreferences = {
  visible_keys: MeasureKey[]; layout: "rows" | "atlas"; period: CircumferencePeriod;
};
export type CircumferenceData = {
  today: string; definitions: CircumferenceDefinition[];
  entries: CircumferenceEntry[]; preferences: CircumferencePreferences;
};
export type MeasurementPoint = { date: string; value: number };
export type MeasurementStats = CircumferenceDefinition & {
  points: MeasurementPoint[]; first: MeasurementPoint | null; last: MeasurementPoint | null;
  count: number; delta: number | null; percent: number | null;
};
export type MeasurementBounds = { start: string; end: string };

const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");

async function request<T>(path = "", method = "GET", body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}/body-circumferences${path}`, {
    method, cache: "no-store", signal,
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail: unknown = payload?.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail)
      ? detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(" · ") : null;
    throw new Error(message || `Körpermaße konnten nicht geladen oder gespeichert werden (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

export const circumferenceApi = {
  get: (signal?: AbortSignal) => request<CircumferenceData>("", "GET", undefined, signal),
  create: (input: CircumferenceInput) => request<CircumferenceEntry>("", "POST", input),
  update: (id: number, input: CircumferenceInput) => request<CircumferenceEntry>(`/${id}`, "PUT", input),
  remove: (id: number) => request<{ deleted: number }>(`/${id}`, "DELETE"),
  preferences: (preferences: CircumferencePreferences) => request<CircumferencePreferences>("/preferences", "PUT", preferences),
};

export const measurementStamp = (date: string) => Date.parse(`${date}T12:00:00Z`);
export const formatCm = (value: number | null | undefined) => value == null || !Number.isFinite(value)
  ? "—" : value.toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
export const signedCm = (value: number | null) => value == null ? "—"
  : `${value > 0 ? "+" : value < 0 ? "−" : ""}${formatCm(Math.abs(value))}`;
export const measurementDate = (date: string, year = false) => new Date(measurementStamp(date)).toLocaleDateString("de-DE", {
  day: "2-digit", month: "2-digit", ...(year ? { year: "numeric" } : {}), timeZone: "UTC",
});

export function measurementBounds(entries: CircumferenceEntry[], period: CircumferencePeriod, today: string): MeasurementBounds {
  const dates = entries.filter(entry => entry.protocol === "standard").map(entry => entry.date).sort();
  const end = dates.at(-1) || today;
  if (period === "all") return { start: dates[0] || end, end };
  const start = new Date(measurementStamp(end)), day = start.getUTCDate();
  start.setUTCDate(1);
  start.setUTCMonth(start.getUTCMonth() - parseInt(period, 10));
  const lastDay = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0)).getUTCDate();
  start.setUTCDate(Math.min(day, lastDay));
  return { start: start.toISOString().slice(0, 10), end };
}

export function measurementStats(definitions: CircumferenceDefinition[], entries: CircumferenceEntry[], bounds: MeasurementBounds): MeasurementStats[] {
  return definitions.map(definition => {
    const points = entries.filter(entry => entry.protocol === "standard" && entry.date >= bounds.start && entry.date <= bounds.end)
      .filter(entry => Number.isFinite(entry.values[definition.key]))
      .map(entry => ({ date: entry.date, value: entry.values[definition.key]! }))
      .sort((a, b) => a.date.localeCompare(b.date));
    const first = points[0] || null, last = points.at(-1) || null;
    const delta = points.length > 1 ? last!.value - first!.value : null;
    return { ...definition, points, first, last, count: points.length, delta, percent: delta == null ? null : 100 * delta / first!.value };
  });
}

export function measurementSegments(points: MeasurementPoint[]): MeasurementPoint[][] {
  const segments: MeasurementPoint[][] = [];
  points.forEach((point, index) => {
    if (!index || measurementStamp(point.date) - measurementStamp(points[index - 1].date) > 14 * 86400000) segments.push([]);
    segments[segments.length - 1].push(point);
  });
  return segments;
}

export function measurementMonths(stats: MeasurementStats[], bounds: MeasurementBounds) {
  const months: string[] = [];
  const date = new Date(measurementStamp(bounds.start));
  date.setUTCDate(1);
  while (date.toISOString().slice(0, 10) <= bounds.end) {
    months.push(date.toISOString().slice(0, 7));
    date.setUTCMonth(date.getUTCMonth() + 1);
  }
  return months.map(month => ({
    month,
    label: new Date(`${month}-15T12:00:00Z`).toLocaleDateString("de-DE", { month: "short", year: "numeric", timeZone: "UTC" }),
    values: stats.map(stat => {
      const point = stat.points.filter(point => point.date.startsWith(month)).at(-1) || null;
      return { key: stat.key, point, delta: point && stat.count > 1 ? point.value - stat.first!.value : null };
    }),
  }));
}
