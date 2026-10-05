export type CoachActionMetric = "sleep" | "steps" | "protein" | "energy";
export type CoachActionStatus = "pending" | "implemented" | "partly" | "not_tried";
type ActionWindow = { start: string; end: string | null; days: number; recorded_days: number; mean: number | null };
export type CoachAction = {
  id: number; action: string; starts_on: string; ends_on: string;
  metric: CoachActionMetric | null; source_report_id: number | null;
  status: CoachActionStatus; status_label: string; note: string | null;
  phase: "running" | "finished"; accepted_at: string; updated_at: string;
  comparison: {
    metric: CoachActionMetric; label: string; unit: string; note: string;
    before: ActionWindow; during: ActionWindow; delta: number | null;
    status: "collecting" | "observed" | "source_changed"; reason: string; method: string;
  } | null;
};
export type CoachActionsData = {
  today: string; entries: CoachAction[];
  metrics: { key: CoachActionMetric; label: string; unit: string; note: string }[];
};
const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}/coach/actions${path}`, { cache: "no-store", ...options });
  if (!response.ok) {
    let message = `Die Wochenmaßnahme konnte nicht gespeichert oder geladen werden (${response.status}).`;
    try {
      const error = await response.json();
      if (typeof error.detail === "string") message = error.detail;
    } catch { /* Keep the concise fallback when no JSON body is available. */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const coachActionsApi = {
  list: (signal?: AbortSignal) => request<CoachActionsData>("", { signal }),
  accept: (action: string, metric: CoachActionMetric | null, reportId: number | null) => request<CoachAction>("", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, metric, source_report_id: reportId }),
  }),
  feedback: (id: number, values: { status?: CoachActionStatus; note?: string | null }) => request<CoachAction>(`/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values),
  }),
  remove: (id: number) => request<{ ok: boolean }>(`/${id}`, { method: "DELETE" }),
};
