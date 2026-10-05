export type BodyProgressObservation = {
  value: number | null; count: number; first_date: string | null; last_date: string | null;
};
export type BodyProgressData = {
  weeks: number; start: string; end: string;
  baseline: { start: string; end: string }; current: { start: string; end: string };
  circumference: {
    key: string; name: string; site: string; baseline: BodyProgressObservation;
    current: BodyProgressObservation; delta: number | null; ignored_measurements: number;
  };
  weight: { baseline: BodyProgressObservation; current: BodyProgressObservation; delta: number | null };
  strength: {
    delta_pct: number | null; groups: number; baseline_exercises: number; current_exercises: number;
    unmatched_exercises: number; changed_exercises: number;
    exercises: { exercise: string; group: string; baseline: BodyProgressObservation;
      current: BodyProgressObservation; delta_pct: number }[];
  };
};

const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");

export async function bodyProgress(weeks: number, measure: string, signal?: AbortSignal): Promise<BodyProgressData> {
  const response = await fetch(`${BASE}/metrics/body/progress?weeks=${weeks}&measure=${measure}`, { cache: "no-store", signal });
  if (!response.ok) throw new Error("Der Körpervergleich konnte nicht geladen werden.");
  return response.json() as Promise<BodyProgressData>;
}
