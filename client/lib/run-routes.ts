export type RunRouteSummary = {
  activity_id: string;
  title: string;
  started_at: string;
  distance_km: number | null;
  duration_seconds: number | null;
  elevation_gain_m: number | null;
  point_count: number;
  matched_external_id: string | null;
};
export type RunRoutePoint = { lat: number; lon: number; altitude_m: number | null; time: string | null };
export type RunRouteDetail = RunRouteSummary & { segments: RunRoutePoint[][] };
export type RunRouteList = {
  items: RunRouteSummary[];
  total: number;
  configured?: boolean;
  sync?: { last_sync: string | null; status: string | null; detail: string | null } | null;
};
type GarminImportResult = {
  mode: "not_configured" | "initial" | "incremental" | "full";
  imported: number; skipped: number; no_route: number; checked: number; errors: number;
  history_limited: boolean; error?: string;
};

const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");

async function request<T>(path: string, signal: AbortSignal, method = "GET"): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { method, signal, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Die Streckendaten konnten nicht geladen werden (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

export const runRoutesApi = {
  list: (offset: number, signal: AbortSignal) => request<RunRouteList>(`/metrics/running/routes?limit=30&offset=${offset}`, signal),
  detail: (id: string, signal: AbortSignal) => request<RunRouteDetail>(`/metrics/running/routes/${encodeURIComponent(id)}`, signal),
  sync: (signal: AbortSignal) => request<GarminImportResult>("/ingest/garmin", signal, "POST"),
};

// Garmin route timestamps already use the application's local wall time.
export function routeDate(value: string): string {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
  if (!match) return "Datum unbekannt";
  return `${match[3]}.${match[2]}.${match[1]}${match[4] ? ` · ${match[4]}:${match[5]}` : ""}`;
}

export type ProjectedRoutePoint = { x: number; y: number };
export type ProjectedRoute = {
  segments: ProjectedRoutePoint[][];
  start: ProjectedRoutePoint;
  end: ProjectedRoutePoint;
  pointCount: number;
  hasExtent: boolean;
  scaleMeters: number;
  scalePixels: number;
};

export function projectRunRoute(segments: RunRoutePoint[][], width = 640, height = 260, padding = 30): ProjectedRoute | null {
  const validSegments: RunRoutePoint[][] = [];
  for (const segment of segments) {
    let current: RunRoutePoint[] = [];
    for (const point of segment) {
      if (!Number.isFinite(point.lat) || !Number.isFinite(point.lon) || Math.abs(point.lat) > 90 || Math.abs(point.lon) > 180) {
        if (current.length) validSegments.push(current);
        current = [];
      } else current.push(point);
    }
    if (current.length) validSegments.push(current);
  }
  const points = validSegments.flat();
  if (!points.length) return null;
  const meanLatitude = points.reduce((sum, point) => sum + point.lat, 0) / points.length;
  const origin = points[0], radians = Math.PI / 180, earthRadius = 6371000;
  const longitudeScale = Math.cos(meanLatitude * radians);
  // Local equirectangular projection: equal meter scales, north up, date-line safe.
  const local = validSegments.map(segment => segment.map(point => ({
    x: (((point.lon - origin.lon + 540) % 360) - 180) * radians * earthRadius * longitudeScale,
    y: -(point.lat - origin.lat) * radians * earthRadius,
  })));
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const segment of local) for (const point of segment) {
    minX = Math.min(minX, point.x); maxX = Math.max(maxX, point.x);
    minY = Math.min(minY, point.y); maxY = Math.max(maxY, point.y);
  }
  const spanX = maxX - minX, spanY = maxY - minY;
  const scale = Math.min((width - padding * 2) / Math.max(spanX, 1), (height - padding * 2) / Math.max(spanY, 1));
  const projected = local.map(segment => segment.map(point => ({
    x: width / 2 + (point.x - (minX + maxX) / 2) * scale,
    y: height / 2 + (point.y - (minY + maxY) / 2) * scale,
  })));
  const scaleTarget = 90 / scale;
  const power = 10 ** Math.floor(Math.log10(scaleTarget));
  const scaleMeters = [5, 2, 1].map(step => step * power).find(step => step <= scaleTarget) || power;
  return {
    segments: projected, start: projected[0][0], end: projected.at(-1)!.at(-1)!,
    pointCount: points.length, hasExtent: Math.max(spanX, spanY) > .01,
    scaleMeters, scalePixels: scaleMeters * scale,
  };
}
