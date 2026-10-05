export type RecoveryMetric = "sleep" | "hrv" | "energy";
export type RecoveryPoint = {
  date: string; predictor: number; value: number; title: string;
  session_id: string; session_count: number; measured_at: string | null; timing_source: string;
};
export type RecoveryPerformance = {
  metric: RecoveryMetric; kind: "run" | "strength"; source: string; days: number;
  predictor_label: string; predictor_unit: string; outcome_label: string; outcome_unit: string;
  timing: "same_day_self_report" | "prior_night";
  groups: {
    package: string; label: string; n: number; points: RecoveryPoint[]; missing: Record<string, number>;
    correlation: number | null; detrended_correlation: number | null; span_days: number;
    statistic: string; status: string; status_label: string; detrended_label: string;
  }[];
  missing_labels: Record<string, string>; method: string; caveat: string;
};

export async function recoveryPerformance(metric: RecoveryMetric, kind: "run" | "strength", source: string,
  signal: AbortSignal): Promise<RecoveryPerformance> {
  const base = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
  const params = new URLSearchParams({ metric, kind, source, days: "180" });
  const response = await fetch(`${base}/metrics/recovery/performance?${params}`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Erholungsanalyse konnte nicht geladen werden.");
  return response.json();
}
