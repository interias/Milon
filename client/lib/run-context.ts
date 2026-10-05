export type RunIntent = "easy" | "long" | "tempo";
export type RunWeather = {
  available: boolean; status: "available" | "empty" | "error" | "never";
  source: "garmin_activity_station"; temperature_c?: number; feels_like_c?: number;
  humidity_pct?: number; wind_from_degrees?: number; wind_speed_kmh?: number | null;
  observed_at?: string; offset_minutes: number | null; time_aligned: boolean;
};
export type RunContextData = {
  activity_id: string; intent: RunIntent | null; training_effort: number | null;
  effort_editable: boolean; effort_conflict: boolean; weather: RunWeather;
};
const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
async function request(id: string, fields?: { intent?: RunIntent | null; training_effort?: number | null }, signal?: AbortSignal): Promise<RunContextData> {
  const response = await fetch(`${BASE}/running/context/${encodeURIComponent(id)}`, {
    method: fields ? "PATCH" : "GET", signal, cache: "no-store",
    headers: fields ? { "Content-Type": "application/json" } : undefined,
    body: fields ? JSON.stringify(fields) : undefined,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : "Laufkontext konnte nicht geladen oder gespeichert werden.");
  }
  return response.json();
}
export const runContextApi = {
  get: (id: string, signal?: AbortSignal) => request(id, undefined, signal),
  update: (id: string, fields: { intent?: RunIntent | null; training_effort?: number | null }) => request(id, fields),
};

export function intentReadout(intent: RunIntent | null, effort: number | null): string {
  if (!intent) return "Ein lockerer Lauf braucht keinen hohen Trainingsreiz. Dein Ziel gibt dem Lauf Kontext.";
  if (intent === "easy") return effort == null ? "Locker geplant · ergänze dein Empfinden, wenn du magst."
    : effort <= 2 ? "Locker geplant und leicht empfunden · Ziel und Gefühl passen zusammen."
    : effort >= 4 ? "Locker geplant, anstrengend empfunden · beim nächsten Vergleich berücksichtigen."
    : "Locker geplant · mittlere Anstrengung empfunden.";
  if (intent === "long") return "Ausdauer im Fokus · Dauer und Pulsverlauf helfen beim Einordnen; schneller ist hier nicht automatisch besser.";
  return "Tempo im Fokus · schnelle Abschnitte und Erholung gemeinsam betrachten. Die Gesamtpace allein bewertet das Training nicht.";
}
