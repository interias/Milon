export type HistoryMetric = { value: number | null; change_to_now: number | null; comparison_note?: string | null; note?: string | null; date?: string | null; days?: number; runs?: number; exercises?: number; sensor_from?: string; status?: string };
export type HistoryPoint = { month: string; as_of: string; partial: boolean; body: HistoryMetric; running: HistoryMetric; strength: HistoryMetric };
export type OverviewHistoryData = { points: HistoryPoint[]; timezone: string; note: string };
export type MonthlyRecapData = { month: string; from_date: string; to_date: string; partial: boolean; running_km: number; runs: number; strength_sessions: number; training_days: number; weight_delta_kg: number | null; weight_first_days: number; weight_last_days: number; routes: { activity_id: string; contour: number[][][] }[]; route_count: number; note: string };

const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
async function read<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}/metrics/overview/${path}`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Der Rückblick konnte nicht geladen werden.");
  return response.json();
}
export const overviewHistory = (signal: AbortSignal) => read<OverviewHistoryData>("history", signal);
export const monthlyRecap = (month: string, signal: AbortSignal) => read<MonthlyRecapData>(`monthly?month=${encodeURIComponent(month)}`, signal);
export const monthLabel = (month: string) => new Date(`${month}-15T12:00:00`).toLocaleDateString("de-DE", { month: "long", year: "numeric" });
