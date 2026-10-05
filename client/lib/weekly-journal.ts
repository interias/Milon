export type JournalDay = {
  date: string;
  runs: { started_at: string; distance_km: number; minutes: number; activity_id: string | null }[];
  strength: { started_at: string; title: string; exercises: string[] }[];
  sleep: { hours: number | null; source: string; label: string; window_hours: number } | null;
  checkin: { energy: number | null; training_effort: number | null } | null;
  steps: number | null;
};
export type WeeklyJournal = {
  timezone: string;
  offset: number;
  from_date: string;
  to_date: string;
  previous_from_date: string;
  previous_to_date: string;
  days: JournalDay[];
  summary: {
    running_km: number;
    running_delta_km: number;
    running_sessions: number;
    strength_sessions: number;
    strength_delta_sessions: number;
    sleep_hours: number | null;
    sleep_nights: number;
    weight_delta_kg: number | null;
    weight_days: number;
    previous_weight_days: number;
    steps_avg: number | null;
    steps_days: number;
    checkin_days: number;
  };
  sources: string[];
  note: string;
};

const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
export async function weeklyJournal(offset: number, signal: AbortSignal): Promise<WeeklyJournal> {
  const response = await fetch(`${BASE}/metrics/activity/journal?offset=${offset}`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Das Wochenjournal konnte nicht geladen werden.");
  return response.json();
}
