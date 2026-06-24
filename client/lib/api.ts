// Typisierter Fetch-Client gegen das Milon-Backend (FastAPI).
// Standard: relativer `/api`-Pfad → Next proxied serverseitig ans Backend (siehe next.config.ts).
// Same-origin, daher kein CORS und keine Firewall-Freigabe für :8000 nötig (auch vom Handy).
// Override per NEXT_PUBLIC_API_URL (z. B. direkte Backend-URL) bleibt möglich.
const BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json() as Promise<T>;
}
async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

async function put<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

// URL eines Fortschritts-Fotos (statisch vom Backend ausgeliefert).
export const mediaUrl = (filename: string) => `${BASE}/media/progress/${filename}`;

// --- Typen (spiegeln die /metrics- & /coach-Antworten) ---
export type BodySummary = {
  weight_kg: number | null; weight_avg7: number | null; weight_delta7: number | null;
  body_fat_pct: number | null; tdee: number | null;
};
export type RunSummary = {
  week_km: number | null; week_runs: number | null; pace: number | null;
  vo2max: number | null; elevation: null;
};
export type Lift = { exercise: string; e1rm: number; peak: number; sets: number };
export type StrengthSummary = {
  top_lift: string | null; top_e1rm: number | null; week_tonnage_kg: number | null;
  rpe: number | null; main_lifts: Lift[];
};
export type Overview = { body: BodySummary; running: RunSummary; strength: StrengthSummary };

export type WeightPoint = { date: string; weight: number | null; ewma: number; avg7: number };
export type WeeklyWeight = { week: string; weight: number };
export type TdeePoint = { date: string; tdee: number; tdee_avg: number; intake: number };
export type StepsPoint = { date: string; steps: number };
export type StepsSummary = { last: number | null; last_day: string | null; avg7: number | null; series: StepsPoint[] };
export type Activity = { kind: "run" | "workout"; date: string; title: string; detail: string };
export type ConsistencyDay = { date: string; level: number; steps: number; trained: boolean };
export type Consistency = {
  days: ConsistencyDay[]; streak: number; active_days: number; trained_days: number; total: number; step_goal: number;
};
export type WeekCompare = {
  days: number;
  running: { current_km: number; previous_km: number; current_runs: number; previous_runs: number; days: number };
  strength: { current_kg: number; previous_kg: number; days: number };
};
export type StepsTrendPoint = { date: string; steps: number; avg7: number };
export type StepsWeek = { week: string; steps: number };
export type CyclingWeek = { week: string; km: number; rides: number };
export type CyclingRide = { date: string; km: number; dur_min: number; speed: number };
export type StepsHealth = {
  last: number | null; last_day: string | null; avg7: number | null;
  avg30: number | null; best: number | null; total_days: number;
};
export type CyclingHealth = {
  total_km: number; rides: number; km_30d: number; avg_speed: number | null; last_day: string | null;
};
export type HealthOverview = { steps: StepsHealth; cycling: CyclingHealth };
export type BodyFatPoint = { date: string; pct: number; avg7: number };
export type MacroSplit = { protein: number; carb: number; fat: number };
export type NutritionSummary = {
  days: number; last_day: string | null; kcal_today: number | null; protein_today: number | null;
  protein_avg7: number | null; protein_target: number | null; protein_per_kg: number;
  kcal_avg7: number | null; tdee: number | null;
  macro_split: MacroSplit | null; macro_g: MacroSplit | null; on_target_days_7: number | null;
};
export type ProteinPoint = { date: string; protein: number; avg7: number };
export type KcalPoint = { date: string; kcal: number; avg7: number };
export type LeanMassPoint = { date: string; weight: number; ffm: number; fat: number };
export type LeanMassSummary = {
  ffm: number | null; fat: number | null; weight: number | null;
  ffm_delta: number | null; fat_delta: number | null; days: number;
};
export type LeanMass = { summary: LeanMassSummary; trend: LeanMassPoint[] };
export type ForecastPoint = { date: string; value: number };
export type Forecast = {
  current?: number; projected?: number; slope_per_day?: number; per_week?: number;
  per_month?: number; horizon_days?: number; fit_days?: number; from_date?: string;
  history?: ForecastPoint[]; points?: ForecastPoint[];
};
export type CompScenario = {
  key: "preserved" | "expected" | "trend"; label: string; p: number;
  weight: number; ffm: number; fat: number; bf_pct: number | null;
  ffm_delta: number; fat_delta: number; note: string | null;
};
export type CompositionForecast = {
  horizon_days: number;
  weight: { current: number; projected: number; per_month: number };
  anchor: { weight: number; bf_pct: number; fat: number; ffm: number };
  scenarios: CompScenario[];
  p_obs: number;
  note: string;
};
export type Tdee = {
  tdee: number | null; avg_intake?: number; weight_change_kg?: number;
  deficit_per_day?: number; window_days?: number; intake_days?: number; reason?: string;
};
export type VolPoint = { week: string; km: number; runs: number };
export type PacePoint = { week: string; pace: number };
export type Vo2Point = { date: string; vo2: number };
export type TonnagePoint = { week: string; tonnage_kg: number };
export type RpePoint = { week: string; rpe: number };
export type E1rmPoint = { date: string; e1rm: number };
export type Exercise = { exercise: string; muscle: string; e1rm: number; peak: number; sets: number; last: string };
export type ExerciseDayPoint = {
  date: string; e1rm: number; top_weight: number; tonnage: number; reps: number; sets: number; rpe: number | null;
};
export type ExerciseStats = {
  sessions: number; sets: number; reps: number; tonnage_kg: number; top_weight: number;
  best_e1rm: number; best_e1rm_date: string; best_set: string; avg_reps: number; avg_rpe: number | null;
  first_date: string; last_date: string;
};
export type ExerciseDelta = { e1rm: number; top_weight: number; tonnage: number; rpe: number | null };
export type ExerciseStatus = {
  status: "progress" | "stall" | "regress" | "deload" | "new" | "unknown";
  label: string; detail: string; e1rm_slope?: number; rpe_slope?: number | null; is_pr?: boolean; sessions?: number;
};
export type ExerciseDetail = {
  exercise: string; muscle: string; period: string;
  stats: ExerciseStats | null; deltas: ExerciseDelta | null; series: ExerciseDayPoint[]; status?: ExerciseStatus;
};
export type PR = {
  date: string; exercise: string; muscle: string; e1rm: number; top_weight: number;
  kind: "e1rm" | "weight" | "both";
};
export type StrengthIndexPoint = { week: string; raw: number; smoothed: number; anchor: number };
export type StrengthDriver = { exercise: string; muscle: string; pct: number };
export type StrengthIndex = {
  value: number; base_week: string; period: string; window_delta_pct: number;
  trend: "steigt" | "stagniert" | "faellt";
  series: StrengthIndexPoint[]; drivers_up: StrengthDriver[]; drivers_down: StrengthDriver[];
  cohort_size: number; groups: number;
};
export type StrengthEnergyPoint = { week: string; index: number; tdee: number; deficit: number };
export type StrengthEnergy = {
  n_weeks: number; tdee_avg: number; deficit_avg: number;
  corr_index_deficit: number | null; corr_change_deficit: number | null; corr_cumulative: number | null;
  recent_weeks: number; recent_index_delta: number; recent_deficit_avg: number;
  prior_deficit_avg: number | null; deficit_deepening: boolean;
  phase: "cut" | "recomp" | "aufbau" | "stabil"; phase_label: string;
  caveat: string; series: StrengthEnergyPoint[];
};
export type ProgressPhotos = { front: string | null; side: string | null; back: string | null; pose1: string | null; pose2: string | null };
export type ProgressEntry = { id: number; taken_on: string; note: string | null; photos: ProgressPhotos; created_at: string | null };
export type SettingsKey = { set: boolean; hint: string };
export type AppSettings = {
  openrouter_model: string; timezone: string; scheduler_enabled: boolean; fddb_user_masked: string;
  keys: { openrouter_api_key: SettingsKey; hevy_api_key: SettingsKey; fddb_pw: SettingsKey; fddb_cookie: SettingsKey; fddb_phpsessid: SettingsKey };
};
export type SettingsUpdate = {
  openrouter_model?: string; scheduler_enabled?: boolean; openrouter_api_key?: string; hevy_api_key?: string;
  fddb_user?: string; fddb_pw?: string; fddb_cookie?: string; fddb_phpsessid?: string;
};
export type Report = { id: number; kind: string; content: string; model: string; created_at: string; tools_used?: string[]; cost_usd?: number | null };
export type CoachStats = {
  model: string; reports_total: number; tokens_total: number;
  cost_total_usd: number; cost_known: boolean; reports_7d: number; cost_7d_usd: number; tokens_7d: number;
};
export type SyncRow = { source: string; last_sync: string | null; status: string | null; detail: string | null };
export type IngestStatus = { enabled: boolean; running: boolean; jobs: { id: string; next_run: string | null }[]; state: SyncRow[] };

export const api = {
  overview: () => get<Overview>("/metrics/overview"),
  // Körper
  bodyWeight: (days = 180) => get<WeightPoint[]>(`/metrics/body/weight?days=${days}`),
  bodyFat: (days = 180) => get<BodyFatPoint[]>(`/metrics/body/bodyfat?days=${days}`),
  bodyTdee: () => get<Tdee>("/metrics/body/tdee"),
  bodyTdeeTrend: (windowDays = 14, days = 180) => get<TdeePoint[]>(`/metrics/body/tdee-trend?window_days=${windowDays}&days=${days}`),
  bodyWeeklyWeight: (weeks = 12) => get<WeeklyWeight[]>(`/metrics/body/weight-weekly?weeks=${weeks}`),
  bodyWeightForecast: (horizon = 30, fitDays = 30) => get<Forecast>(`/metrics/body/weight-forecast?horizon=${horizon}&fit_days=${fitDays}`),
  bodyFatForecast: (horizon = 30, fitDays = 30) => get<Forecast>(`/metrics/body/bodyfat-forecast?horizon=${horizon}&fit_days=${fitDays}`),
  bodyCompositionForecast: (horizon = 30, fitDays = 30) => get<CompositionForecast>(`/metrics/body/composition-forecast?horizon=${horizon}&fit_days=${fitDays}`),
  bodyLeanMass: (days = 180) => get<LeanMass>(`/metrics/body/lean-mass?days=${days}`),
  // Ernährung
  nutritionSummary: () => get<NutritionSummary>("/metrics/nutrition/summary"),
  nutritionProtein: (days = 30) => get<ProteinPoint[]>(`/metrics/nutrition/protein?days=${days}`),
  nutritionKcal: (days = 30) => get<KcalPoint[]>(`/metrics/nutrition/kcal?days=${days}`),
  bodySteps: (days = 14) => get<StepsSummary>(`/metrics/body/steps?days=${days}`),
  activityRecent: (limit = 8) => get<Activity[]>(`/metrics/activity/recent?limit=${limit}`),
  activityConsistency: (days = 140) => get<Consistency>(`/metrics/activity/consistency?days=${days}`),
  activityCompare: (days = 7) => get<WeekCompare>(`/metrics/activity/compare?days=${days}`),
  bodySummary: () => get<BodySummary>("/metrics/body/summary"),
  // Gesundheit (Schritte + Radfahren)
  healthOverview: () => get<HealthOverview>("/metrics/health/overview"),
  healthSteps: (days = 30) => get<StepsTrendPoint[]>(`/metrics/health/steps?days=${days}`),
  healthStepsWeekly: (weeks = 12) => get<StepsWeek[]>(`/metrics/health/steps-weekly?weeks=${weeks}`),
  healthCycling: (weeks = 12) => get<CyclingWeek[]>(`/metrics/health/cycling?weeks=${weeks}`),
  healthCyclingRecent: (limit = 8) => get<CyclingRide[]>(`/metrics/health/cycling-recent?limit=${limit}`),
  // Laufen
  runSummary: () => get<RunSummary>("/metrics/running/summary"),
  runVolume: (weeks = 26) => get<VolPoint[]>(`/metrics/running/volume?weeks=${weeks}`),
  runPace: (weeks = 26) => get<PacePoint[]>(`/metrics/running/pace?weeks=${weeks}`),
  runVo2: (days = 365) => get<Vo2Point[]>(`/metrics/running/vo2?days=${days}`),
  // Kraft
  strengthSummary: () => get<StrengthSummary>("/metrics/strength/summary"),
  strengthTonnage: (weeks = 26) => get<TonnagePoint[]>(`/metrics/strength/tonnage?weeks=${weeks}`),
  strengthRpe: (weeks = 26) => get<RpePoint[]>(`/metrics/strength/rpe?weeks=${weeks}`),
  strengthE1rm: (exercise: string, weeks = 26) =>
    get<E1rmPoint[]>(`/metrics/strength/e1rm?exercise=${encodeURIComponent(exercise)}&weeks=${weeks}`),
  strengthExercises: () => get<Exercise[]>("/metrics/strength/exercises"),
  strengthExercise: (name: string, period = "all") =>
    get<ExerciseDetail>(`/metrics/strength/exercise?name=${encodeURIComponent(name)}&period=${period}`),
  strengthRecords: (days = 120, limit = 25) => get<PR[]>(`/metrics/strength/records?days=${days}&limit=${limit}`),
  strengthIndex: (period = "3m") => get<StrengthIndex>(`/metrics/strength/index?period=${period}`),
  strengthEnergy: () => get<StrengthEnergy>(`/metrics/strength/energy`),
  // Coach
  coachReports: (limit = 10) => get<Report[]>(`/coach/reports?limit=${limit}`),
  coachDaily: () => post<Report>("/coach/daily"),
  coachWeekly: () => post<Report>("/coach/weekly"),
  coachChat: (message: string, history?: { role: string; content: string }[]) =>
    post<Report>("/coach/chat", { message, history }),
  coachAsk: (message: string, history?: { role: string; content: string }[]) =>
    post<Report>("/coach/ask", { message, history }),
  coachStats: () => get<CoachStats>("/coach/stats"),
  // Ingest / Sync
  ingestStatus: () => get<IngestStatus>("/ingest/status"),
  ingestRefresh: () => post<Record<string, unknown>>("/ingest/refresh"),
  // Fortschritts-Fotos
  progressList: () => get<ProgressEntry[]>("/progress"),
  progressCreate: async (form: FormData): Promise<ProgressEntry> => {
    const r = await fetch(`${BASE}/progress`, { method: "POST", body: form });
    if (!r.ok) throw new Error(`/progress → ${r.status}`);
    return r.json() as Promise<ProgressEntry>;
  },
  progressUpdate: async (id: number, form: FormData): Promise<ProgressEntry> => {
    const r = await fetch(`${BASE}/progress/${id}`, { method: "PUT", body: form });
    if (!r.ok) throw new Error(`/progress/${id} → ${r.status}`);
    return r.json() as Promise<ProgressEntry>;
  },
  progressDelete: async (id: number) => {
    const r = await fetch(`${BASE}/progress/${id}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`/progress/${id} → ${r.status}`);
    return r.json();
  },
  // Einstellungen
  settingsGet: () => get<AppSettings>("/settings"),
  settingsUpdate: (body: SettingsUpdate) => put<AppSettings>("/settings", body),
};
