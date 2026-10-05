export type SourceHealth = "ok" | "partial" | "error" | "never" | "old" | "not_configured";
export type SourceStatusData = {
  generated_at: string;
  scheduler_enabled: boolean;
  resting_hr_note: string;
  sources: {
    key: string;
    label: string;
    purpose: string;
    status: SourceHealth;
    last_attempt_at: string | null;
    last_success_at: string | null;
    latest_data_date: string | null;
    data_old: boolean;
    note: string;
    categories: { key: string; label: string; status: "available" | "empty" | "error" | "unsupported" | "never"; last_attempt_at: string | null; last_success_at: string | null }[];
  }[];
};

export async function getSourceStatus(signal: AbortSignal): Promise<SourceStatusData> {
  const base = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
  const response = await fetch(`${base}/metrics/sources`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Der Quellenstatus konnte nicht geladen werden.");
  return response.json();
}
