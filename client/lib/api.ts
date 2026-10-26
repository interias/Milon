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

// Wie put/post, aber mit der Server-Meldung (detail) als Fehlertext — für Formulare mit 409/422.
async function send<T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const detail = await r.json().then((j) => j?.detail).catch(() => null);
    throw new Error(typeof detail === "string" ? detail : `${path} → ${r.status}`);
  }
  return r.json() as Promise<T>;
}

// URL eines Fortschritts-Fotos (statisch vom Backend ausgeliefert).
export const mediaUrl = (filename: string) => `${BASE}/media/progress/${filename}`;
// Zwift-Workout (.zwo) einer Plan-Einheit, über den /api-Proxy.
export const bikeZwoUrl = (id: number) => `${BASE}/bike-plan/session/${id}.zwo`;
// Strecken-Download eines entdeckten Verlieses (GPX-Track bzw. FIT-Course), über den /api-Proxy.
export const dungeonFileUrl = (key: string, ext: "gpx" | "fit") => `${BASE}/hero/world/dungeon/${encodeURIComponent(key)}.${ext}`;
// Live-Endpunkte der Expedition: Token im Header X-Hero-Token (nur auf dem Gerät, nie im Code).
export class LiveError extends Error {
  constructor(public status: number, path: string) { super(`${path} → ${status}`); }
}
async function live<T>(token: string, method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method, cache: "no-store",
    headers: { "X-Hero-Token": token, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new LiveError(r.status, path);
  return r.json() as Promise<T>;
}
export const coachImageUrl = (path: string) => `${BASE}${path}`;

// --- Typen (spiegeln die /metrics- & /coach-Antworten) ---
export type BodySummary = {
  weight_kg: number | null; weight_avg7: number | null; weight_delta7: number | null;
  body_fat_pct: number | null; tdee: number | null;
  weight_date: string | null; weight_days7: number; previous_weight_days7: number;
};
export type RunSummary = {
  week_km: number | null; week_runs: number | null; pace: number | null;
  vo2max: number | null; avg_hr: number | null; max_hr: number | null;
  ef: number | null; hr_drift: number | null; hr_week: string | null; elevation: null;
};
export type Lift = { exercise: string; e1rm: number; peak: number; sets: number };
export type StrengthSummary = {
  top_lift: string | null; top_e1rm: number | null; week_tonnage_kg: number | null;
  rpe: number | null; main_lifts: Lift[];
};
export type Overview = { body: BodySummary; running: RunSummary; strength: StrengthSummary };

export type WeightPoint = { date: string; weight: number | null; ewma: number; avg7: number | null };
export type WeeklyWeight = { week: string; weight: number };
export type TdeePoint = { date: string; tdee: number; tdee_avg: number; intake: number; intake_avg: number; estimate_days: number };
export type StepsPoint = { date: string; steps: number };
export type StepsSummary = { last: number | null; last_day: string | null; avg7: number | null; series: StepsPoint[] };
export type Activity = { kind: "run" | "workout" | "ride"; date: string; title: string; detail: string };
export type WeatherInfo = { code: number | null; icon: string; text: string };
export type WeatherHour = WeatherInfo & { time: string; temp: number; rain_prob: number | null; rain_mm: number; wind_kmh: number | null; is_day: boolean };
export type RunWindow = {
  start: string; end: string; temp: number; rain_prob: number; wind_kmh: number; wet: boolean; score: number; rating: "ideal" | "gut" | "mäßig";
  clothing: { level: string; text: string; extras: string[]; felt: number; adjust: number };
};
export type RunAdvice = { day: "heute" | "morgen"; date: string; sunrise: string; sunset: string; morning: RunWindow | null; best: RunWindow | null; notes: string[] };
export type Weather = { configured: false } | {
  configured: true; place: string; index: number; places: string[]; run: RunAdvice | null; date: string; now_hour: string | null;
  days: (WeatherInfo & { date: string; temp_max: number; temp_min: number; rain_prob_max: number | null })[]; source: string; hours: WeatherHour[];
  current: WeatherInfo & { temp: number; feels_like: number; wind_kmh: number; is_day: boolean };
  day: WeatherInfo & { temp_max: number; temp_min: number; rain_mm: number; rain_prob_max: number | null; wind_max_kmh: number | null; sunrise: string; sunset: string };
};
export type ConsistencyDay = { date: string; level: number; steps: number; trained: boolean; ride?: boolean; sick?: boolean };
export type Consistency = {
  days: ConsistencyDay[]; streak: number; active_days: number; trained_days: number; sick_days?: number; total: number; step_goal: number;
};
export type WeekCompare = {
  days: number;
  running: { current_km: number; previous_km: number; current_runs: number; previous_runs: number; days: number };
  strength: { current_kg: number; previous_kg: number; days: number };
  cycling?: { current_sessions: number; previous_sessions: number; current_minutes: number; previous_minutes: number; days: number };
};
export type EnduranceDay = { date: string; load: number; ctl: number; atl: number; tsb: number };
export type EnduranceWeek = { week: string; run: number; bike: number; total: number; run_share: number | null; runs: number; rides: number; unrated: number };
export type EnduranceSession = { date: string; sport: "run" | "bike"; minutes: number; avg_hr: number | null; trimp: number | null; activity_id: string | null; note: string | null };
export type EnduranceFitness = {
  days: number; ctl_days: number; atl_days: number; hr_rest: number; hr_max: number; history_days: number;
  today: (EnduranceDay & { form: string | null; has_load_today: boolean }) | null;
  series: EnduranceDay[]; weeks: EnduranceWeek[]; sessions: EnduranceSession[];
  unrated: { runs: number; rides: number }; caveat: string;
};
export type StepsTrendPoint = { date: string; steps: number | null; avg7: number | null; days7: number };
export type StepsWeek = { week: string; steps: number | null; days: number };
export type CyclingWeek = { week: string; km: number; rides: number };
export type CyclingRide = { date: string; km: number; dur_min: number; speed: number };
export type StepsHealth = {
  days7: number; days30: number; window_start: string | null; source_label: string; provisional_day?: boolean;
  last: number | null; last_day: string | null; avg7: number | null;
  avg30: number | null; best: number | null; total_days: number;
};
export type CyclingHealth = {
  last_ride: CyclingRide | null; window_start: string; to_date: string;
  total_km: number; rides: number; km_30d: number; avg_speed: number | null; last_day: string | null;
};
export type HealthOverview = { steps: StepsHealth; cycling: CyclingHealth };
export type BodyFatPoint = { date: string; pct: number | null; avg7: number | null };
export type BodyFatBand = { series: { date: string; median: number | null; low: number | null; high: number | null; days: number }[]; window_days: number; minimum_days: number; note: string };
export type SleepPoint = { external_id: string; date: string; started_at: string; ended_at: string; asleep_hours: number | null; window_hours: number; awake_minutes: number | null; nap: boolean; main_sleep: boolean; source_package: string; stage_coverage: number | null };
export type SleepOverview = { summary: { latest_date: string | null; latest_asleep_hours: number | null; latest_window_hours: number | null; avg_asleep_hours_7d: number | null; nights_7d: number; known_asleep_nights_7d: number; naps_7d: number }; series: SleepPoint[]; sources: { package: string; label: string; nights: number; known_asleep_nights: number }[]; switch_date: string | null; method: string; notes: string[] };
export type SleepPerformancePoint = { date: string; sleep_hours: number; value: number; title: string; session_id: string };
export type SleepPerformance = { kind: "run" | "strength"; outcome_label: string; outcome_unit: string; source: string; groups: { package: string; label: string; n: number; correlation: number | null; ci95: [number, number] | null; status: string; status_label: string; points: SleepPerformancePoint[]; missing: { no_sleep: number; unknown_sleep: number; no_outcome: number; excluded: number } }[]; method: string; caveat: string };
export type WeeklyReview = { activity: ActivityOverview; weight: { delta_kg: number | null; current_days: number; previous_days: number }; sleep: { avg_hours: number | null; measured_nights: number; recorded_nights: number }; checkins: { days: number; count: number; energy_avg: number | null; energy_days: number }; note: string };
export type MacroSplit = { protein: number; carb: number; fat: number };
export type NutritionSummary = {
  window_start: string | null; recorded_days_7: number; protein_days_7: number; kcal_days_7: number;
  days: number; last_day: string | null; kcal_today: number | null; protein_today: number | null;
  protein_avg7: number | null; protein_target: number | null; protein_per_kg: number;
  kcal_avg7: number | null; tdee: number | null;
  macro_split: MacroSplit | null; macro_g: { protein: number | null; carb: number | null; fat: number | null } | null; on_target_days_7: number | null;
};
export type ProteinPoint = { date: string; protein: number | null; avg7: number | null; days7: number };
export type KcalPoint = { date: string; kcal: number | null; avg7: number | null; days7: number };
export type LeanMassPoint = { date: string; weight: number | null; ffm: number | null; fat: number | null; paired_days: number };
export type LeanMassSummary = {
  ffm: number | null; fat: number | null; weight: number | null;
  ffm_delta: number | null; fat_delta: number | null; days: number;
  from_date?: string; to_date?: string; measurement_days: number;
};
export type LeanMass = { summary: LeanMassSummary; trend: LeanMassPoint[] };
export type ForecastPoint = { date: string; value: number };
export type Forecast = {
  available: boolean; reason?: string; observed_days?: number; span_days?: number;
  min_observed_days?: number; min_span_days?: number;
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
  available: boolean; reason?: string;
  from_date?: string;
  horizon_days?: number;
  weight?: { current: number; projected: number; per_month: number };
  anchor?: { weight: number; bf_pct: number; fat: number; ffm: number };
  scenarios?: CompScenario[];
  p_obs?: number;
  note?: string;
};
export type Tdee = {
  from_date?: string;
  estimate_days?: number; smooth_days?: number; provisional?: boolean;
  tdee: number | null; avg_intake?: number; weight_change_kg?: number;
  deficit_per_day?: number; window_days?: number; intake_days?: number; reason?: string;
};
export type RunWeekOverview = {
  week_start: string; previous_week_start: string;
  current: { km: number; runs: number; minutes: number };
  previous: { km: number; runs: number; minutes: number };
};
export type ActivityOverview = {
  from_date: string; to_date: string; previous_from_date: string; previous_to_date: string;
  running: { current_km: number; previous_km: number };
  strength: { current_sessions: number; previous_sessions: number };
  cycling?: { current_sessions: number; previous_sessions: number; current_minutes: number; previous_minutes: number };
  steps: { current_avg: number | null; previous_avg: number | null; current_days: number; previous_days: number };
};
export type VolPoint = { week: string; km: number; runs: number };
export type PacePoint = { week: string; pace: number };
export type Vo2Point = { date: string; vo2: number };
export type BestEffortEntry = { seconds: number; pace: number; date: string };
export type BestEffortDist = { distance_m: number; km: number; label: string; entries: BestEffortEntry[] };
export type RunRecords = {
  longest_run?: { km: number; date: string };
  best_ef?: { ef: number; date: string };
  biggest_week?: { km: number; week: string; runs: number };
};
export type BestEfforts = { distances: BestEffortDist[]; top: number; records?: RunRecords };
export type Rarity = "grau" | "weiss" | "gruen" | "blau" | "lila" | "orange" | "rot";
export type Achievement = {
  id: string; category: string; name: string; desc: string; points: number; icon: string;
  rarity: Rarity; rarity_label: string; flavor: string;
  earned: boolean; earned_date: string | null;
  progress: number; progress_label: string | null;
};
export type AchievementSummary = {
  points: number; points_possible: number; earned: number; total: number;
  rarity_counts: Record<Rarity, { earned: number; total: number }>;
  level: number; title: string; floor: number; next_points: number | null;
  to_next: number; progress: number;
};
export type Achievements = { achievements: Achievement[]; summary: AchievementSummary };

export type HeroItem = {
  id: string; name: string; slot: string; slot_label: string; rarity: Rarity; rarity_label: string;
  ilvl: number; flavor: string; source: "beute" | "truhe" | "veteran" | "auftrag" | "boss" | "instanz" | "taeglich" | "event" | "auktion" | "gipfel"; reason: string; date: string;
  lucky?: boolean; run_km?: number; ride_min?: number; claimed_at?: string; equipped?: boolean;
  set?: string | null; upgrades?: number; upgrade_cost?: number | null; dust?: number; price?: number; mail?: boolean;
};
export type HeroVaultSlot = { slot: number; threshold: number; unlocked: boolean; item: HeroItem };
export type HeroVault = {
  week: string; runs: number; rides?: number; sick_days: number; slots: HeroVaultSlot[]; complete: boolean; claimed_slot: number | null;
  stone_level?: number | null;
};
export type HeroBuff = { key: string; name: string; kind: "buff" | "debuff"; icon: string; effect: string; source: string };
export type HeroDaily = { date: string; key: string; title: string; goal: string; done: boolean; sick: boolean };
export type HeroSaga = { created_at: string; week: string | null; content: string; cost_usd: number | null };
export type HeroBag = { id: string; name: string; slots: number; date: string; source: string };
export type HeroAttribute = { key: string; label: string; source: string; score: number | null; value: string; delta: number | null };
// Eigene, per GPX importierte Strecke (privat): Verlies oder gelaufene Spur – ohne Koordinaten.
export type HeroOwnRoute = { id: string; kind: "dungeon" | "track"; name: string; own: true; length_km: number; created_on: string;
  day?: string; superseded?: boolean; key?: string; level?: number; region?: string | null; segments?: number; discovered?: boolean; cleared?: boolean };
export type HeroTile = { key: string; x: number; y: number; w: number; h: number };
export type HeroDungeon = { id: string; key: string; name: string; type: string; type_label: string; desc: string; x: number; y: number;
  km: number; length_km: number; region: string | null; level: number; xp: number; gold: number; discovered: boolean; discovered_on: string | null;
  cleared: boolean; cleared_on: string | null; heroic: boolean; heroic_on: string | null; loot: string; closest_m?: number | null; provisional?: boolean; own?: boolean;
  segments: { boss: string; points: [number, number][]; coverage: number; cleared: boolean; cleared_on: string | null; xp: number; live_coverage?: number; provisional?: boolean }[] };
export type HeroPlace = { id: string; kind: "schrein" | "schatz"; kind_label: string; name: string; region: string; ring: number;
  x: number; y: number; km: number; level: number; xp: number; gold: number; loot: string | null; reach_m: number; found: boolean; found_on: string | null; via?: "fuss" | "rad" | null; closest_m?: number | null; provisional?: boolean };
export type HeroLiveFind = { kind: "gebiet" | "schrein" | "schatz" | "abschnitt" | "verlies_entdeckt" | "verlies"; id: string; name: string; xp: number; provisional: true };
export type HeroLiveTarget = { kind: "poi" | "dungeon"; id: string; name: string; chosen: boolean; label: string; level: number; bearing_deg: number | null; distance_m: number | null };
export type HeroKeystoneAffix = { key: string; name: string; desc: string; kind?: "gewaehlt" | "woche" | "wetter" };
export type HeroLiveKeystone = {
  id: number; dungeon: string; name: string; level: number; affixes: HeroKeystoneAffix[]; time_limit_s: number;
  clock_started: boolean; remaining_s: number | null; segments: { boss: string; coverage: number; cleared: boolean }[];
  segments_cleared: number; segments_total: number; provisional: boolean;
};
export type HeroKeystonePreview = {
  dungeon: string; name: string; length_km: number; key_level: number; max_level: number; levels: number[];
  suggested_level: { level: number; source: string; reason: string }; easy_pace: { pace: number | null; runs: number; source: string };
  time_limits: Record<string, number>; week_affix: HeroKeystoneAffix; affixes: HeroKeystoneAffix[];
};
export type HeroLiveEvent = {
  id: number; kind: "schatz" | "begleiter" | "wegelagerer" | "totem"; name: string; text: string; level: number;
  status: "active" | "reached" | "missed" | "declined" | "confirmed" | "rejected" | "expired"; provisional: boolean;
  bearing_deg: number | null; distance_m: number | null; remaining_s: number | null; radius_m?: number; progress?: number;
  reward: { xp: number; loot: string | null } | null;
};
export type HeroMythic = {
  dungeons: { dungeon: string; name: string; own: boolean; best_level: number; timed_runs: number; best_date: string | null }[];
  total: number; best_level: number; dungeons_timed: number; timed_runs: number;
};
export type HeroLiveState = {
  keystone?: HeroLiveKeystone | null; event?: HeroLiveEvent | null;
  session: string; available: boolean; active: boolean; points: number; first_ts: number | null; last_ts: number | null;
  revealed: { cells: number; km2: number }; finds: HeroLiveFind[]; target: HeroLiveTarget | null;
  dungeon: { id: string; name: string; discovered: boolean; cleared: boolean; provisional: boolean; provisional_cleared: boolean;
    segments: { boss: string; coverage: number; cleared: boolean; provisional: boolean }[] } | null;
};
export type HeroLiveOverlay = { sessions: string[]; cells: [number, number][]; routes: { session: string; date: string; points: [number, number][] }[]; km2: number };

export type HeroPeak = { key: string; name: string; hm: number; xp: number; loot: string; reached: boolean; reached_on: string | null; progress: number };
export type HeroClimb = { total_hm: number; rides: number; peaks: HeroPeak[];
  rounds: { n: number; name: string; hm: number; reached_on: string; xp: number }[]; next: HeroPeak | null; next_in_hm: number };
export type HeroDreams = { worlds: { world: string; known: boolean; rides: number; route_count: number; routes: { route: string; rides: number }[];
    km: number; hm: number; first_on: string; last_on: string }[];
  known: string[]; visited_known: number; known_total: number; all_worlds: boolean; total_hm: number; best_routes: number;
  route_tiers: number[]; hm_tiers: { hm: number; reached: boolean }[] };
export type Hero = {
  today: string; start: string;
  hero: {
    level: number; title: string; xp: number; floor: number; next: number; progress: number;
    class: string; class_label: string; class_color: string; class_desc: string;
    spec: string | null; spec_label: string | null; spec_desc: string;
    spec_scores: Record<string, number>; shares: { laufen: number; rad?: number; kraft: number; alltag: number };
    rested: number; rested_cap: number; week_xp: number;
    spec_auto: string | null; spec_chosen: string | null; title_chosen: string | null;
  };
  xp_sources: Record<"laufen" | "kraft" | "alltag" | "erfolge" | "ruhebonus" | "buffs" | "fokus" | "talente" | "auftraege" | "bosse" | "instanzen" | "taeglich" | "event" | "duelle" | "erkundung" | "events" | "rad" | "gipfel", number>;
  duels: { won: number; total: number;
    last: { date: string; km: number; pace: number; ef: number | null; twin_date: string; twin_km: number; twin_pace: number; twin_ef: number | null; won: boolean; xp: number } | null;
    shadows: { label: string; available: boolean; appears?: string | null; wins?: number; won?: boolean;
      rows?: { key: string; name: string; now: number | null; then: number | null; better: boolean | null }[] }[] };
  mounts: { key: string; name: string; kind: string; need: number; glyph: string; value: number; unlocked: boolean; unlocked_on: string | null; chosen: boolean; unit: string; ride_km?: number; level?: number }[];
  climb?: HeroClimb;
  dreams?: HeroDreams;
  daily: { streak: number; today: HeroDaily | null; last7: HeroDaily[] } | null;
  event: { month: string; name: string; token: string; item: string; effect: string; tokens: number; goal: number; done: boolean; done_on: string | null; xp: number; rule: string } | null;
  trainer: { name: string; role: string; quote: string };
  bosses: { key: string; name: string; kind: string; goal: string; status: string; hp: number; defeated: boolean; defeated_on: string | null; xp: number; loot: string; month: string }[];
  dungeons: { id: string; name: string; tier: string; tier_label: string; loot: string; date: string; km: number; cleared: boolean; xp: number;
    bosses: { name: string; km: number | null; defeated: boolean; optional?: boolean; hint?: string }[] }[];
  talents: { level: number; name: string; unlocked: boolean; chosen: string | null; options: { key: string; name: string; effect: string; icon: string }[] }[];
  quests: { week: string; halved: boolean; sick_days: number; complete: boolean; complete_on: string | null;
    quests: { id: string; category: string; title: string; goal: string; target: number; unit: string; progress: number; done: boolean; done_on: string | null; xp: number }[] } | null;
  buffs: HeroBuff[];
  companion: { species: string; name: string; stage: number; stage_label: string; streak: number; next_stage: number | null; mood: string; text: string };
  specs: { key: string; label: string; desc: string; focus: string; score: number | null }[];
  attributes: HeroAttribute[];
  progression: { week: string; laufen: number; kraft: number; alltag: number; erfolge: number; ruhebonus: number; buffs: number; fokus: number; talente: number; auftraege: number; bosse: number; instanzen: number; taeglich: number; event: number; duelle: number; erkundung: number; events?: number; rad?: number; gipfel?: number; xp: number; level: number }[];
  mythic?: HeroMythic | null;
  vault: { current: HeroVault; claimable: HeroVault[]; veteran: HeroVault | null };
  inventory: HeroItem[];
  equipment: Record<string, HeroItem>;
  dust: number;
  gold: { balance: number; earned: number; sold: number; spent: number; week: number; sources: Record<string, number>; rates: Record<string, number> };
  auction: { week: string; ends: string; listings: { idx: number; kind: string; price: number; sold: boolean; item?: HeroItem;
    bag?: { id: string; name: string; slots: number; source: string }; mount?: { key: string; name: string; glyph: string } }[] } | null;
  world: { available: false } | { available: true; cell_m: number; radius_m: number; core_m: number; cells: [number, number][];
    routes: { date: string; points: [number, number][] }[]; rides?: { date: string; points: [number, number][] }[]; rings: { name: string; outer_m: number }[];
    regions: { name: string; ring: number; ring_label: string; xp: number; gold: number; cells: number; total: number; pct: number; discovered: boolean; discovered_on: string | null; via?: "fuss" | "rad" | null }[];
    pois: HeroPlace[]; dungeons: HeroDungeon[];
    explored_pct: number; km2: number; live?: HeroLiveOverlay | null };
  potions: { key: string; name: string; effect: string; price: number; glyph: string; count: number; active_today: boolean }[];
  bags: { capacity: number; backpack: number; max_bags: number; used: HeroBag[]; spare: HeroBag[] };
  sets: { name: string; suffix: string; owned: number; equipped: number; color: string; bonus: string | null }[];
  titles: { key: string; name: string; condition: string; value: number; target: number; earned: boolean; chosen: boolean }[];
  reputation: { key: string; name: string; source: string; value: number; standing: string; rank: number; floor: number; next: number | null; progress: number }[];
  ilvl_avg: number | null;
  log: { date: string; kind: "level" | "klasse" | "erfolg" | "beute" | "truhe" | "auftrag" | "boss" | "instanz" | "event" | "duell" | "reittier" | "tasche" | "erkundung" | "verlies" | "abschnitt" | "schrein" | "schatz" | "fahrt" | "gipfel"; text: string; rarity?: Rarity; name?: string; level?: number; km?: number; xp?: number; item_id?: string; tip?: string[] | null }[];
  rules: { runs_full_xp: number; workouts_full_xp: number; rest_per_day: number; vault_thresholds: number[] };
};
export type PaceDetail = {
  series?: { date: string; pace: number; smooth: number }[];
  current?: number; runs?: number; caveat?: string;
};
export type HrPoint = {
  week: string; avg_hr: number; max_hr: number | null; ef: number | null;
  drift: number | null; runs: number;
};
export type TrendVerdict = "besser" | "schlechter" | "unklar" | "wenig_daten";
export type FitTrend = {
  verdict: TrendVerdict; label: string; significant?: boolean; n?: number; days?: number;
  r2?: number; slope_per_week?: number; ci_per_week?: number; delta?: number;
  delta_sec_per_km?: number | null; sec_per_km_per_month?: number | null;
};
export type PaceAtHr = {
  ref_hr?: number; window_weeks?: number; series?: { week: string; pace: number | null }[];
  points?: number; current?: number | null; trend?: FitTrend; caveat?: string;
};
export type EasyHr = {
  pace_lo?: number; pace_hi?: number; runs?: number;
  series?: { week: string; avg_hr: number; runs: number }[]; trend?: FitTrend; caveat?: string;
};
export type Trimp = {
  hr_rest?: number; hr_max?: number; series?: { week: string; trimp: number; runs: number }[];
  avg4?: number | null; caveat?: string;
};
export type RestingHr = {
  series?: { date: string; bpm: number; avg7: number }[]; last?: number; last_day?: string;
  avg7?: number; trend_days?: number; trend?: FitTrend;
};
export type EfTrend = {
  series?: { date: string; ef: number; smooth: number }[];
  current?: number; runs?: number; trend?: FitTrend; caveat?: string;
};
export type PaceByZone = {
  hr_max?: number; hr_max_source?: "einstellung" | "daten" | "standard"; weeks?: string[];
  zones?: { zone: string; name: string; idx: number; lo: number; hi: number | null; pct: string;
            runs: number; series: (number | null)[]; smooth?: (number | null)[];
            sec_per_km_per_month?: number | null }[];
  hidden_runs?: number; caveat?: string;
};
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
export type PlanSet = { type: "warmup" | "normal"; weight_kg: number | null; reps: number; rpe: number | null };
export type PlanExercise = {
  key: string; name: string; template_id: string; rep_range: [number, number]; rest_seconds: number;
  superset: number | null; weight_kg: number | null; step_up_kg: number | null; sets: PlanSet[];
  action: "increase" | "hold" | "decrease" | "deload" | "pause" | "start" | "new";
  reason: string; rir_note: string; last: { date: string; summary: string } | null;
};
export type TrainingPlan = {
  key: string; title: string; name: string; per_week: number; done: number;
  last_date: string | null; duration_min: number; exercises: PlanExercise[];
};
export type MuscleVolume = { muscle: string; this_week: number; avg_4w: number; planned: number };
export type WeeklyVolume = { week_start: string; band: [number, number]; muscles: MuscleVolume[] };
export type NextTraining = { date: string; week_start: string; next: string | null; plans: TrainingPlan[] };
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
export type CoachGoal = {
  id: string; name: string; start_date: string | null; end_date: string | null; target: string;
  priority: "high" | "normal" | "low"; status: "active" | "achieved" | "archived";
  effective_status: "active" | "past" | "achieved" | "archived";
};
export type CoachProfile = { context: string; goals: CoachGoal[] };
export type CoachProfileUpdate = { context: string; goals: Omit<CoachGoal, "effective_status">[] };
export type LlmBudget = {
  month: string; budget_usd: number; spent: { anthropic: number; openrouter: number };
  ratio: number; warn: boolean; exceeded: boolean;
};
export type AppSettings = {
  openrouter_model: string; llm_provider: "" | "anthropic" | "openrouter"; llm_provider_resolved: "anthropic" | "openrouter";
  anthropic_model: string; anthropic_effort: "low" | "medium" | "high"; llm_monthly_budget_usd: number; llm_budget: LlmBudget;
  timezone: string; scheduler_enabled: boolean; run_hr_max: number; bike_ftp: number; weather_places: string[]; fddb_user_masked: string;
  keys: { anthropic_api_key: SettingsKey; openrouter_api_key: SettingsKey; hevy_api_key: SettingsKey; fddb_pw: SettingsKey; fddb_cookie: SettingsKey; fddb_phpsessid: SettingsKey };
};
export type SettingsUpdate = {
  openrouter_model?: string; llm_provider?: string; anthropic_model?: string; anthropic_effort?: string;
  llm_monthly_budget_usd?: number; anthropic_api_key?: string; scheduler_enabled?: boolean; run_hr_max?: number; bike_ftp?: number; weather_places?: string[]; openrouter_api_key?: string; hevy_api_key?: string;
  fddb_user?: string; fddb_pw?: string; fddb_cookie?: string; fddb_phpsessid?: string;
};
export type CoachVisual = { id: "weight" | "running" | "strength" | "sleep"; title: string; kind: "line" | "bars"; unit: string; description: string; captured_at: string; points: { date: string; value: number | null }[] };
export type CoachImage = { url: string; cost_usd: number | null; model: string };
export type Report = { id: number; kind: string; content: string; model: string; created_at: string; tools_used?: string[]; cost_usd?: number | null; provider?: string | null; fallback_reason?: string | null; visuals?: CoachVisual[] };
export type Briefing = { id: number; kind: "briefing"; content: string; created_at: string; model: string | null; provider: string | null; fallback_reason: string | null; cost_usd: number | null };
export type BriefingToday = { date: string; briefing: Briefing | null };
export type WeeklyAutoReport = Omit<Briefing, "kind"> & { kind: "weekly-auto" };
export type WeeklyAutoCurrent = { week_from: string; week_to: string; report: WeeklyAutoReport | null };
export type CoachStats = {
  model: string; reports_total: number; tokens_total: number;
  cost_total_usd: number; cost_known: boolean; reports_7d: number; cost_7d_usd: number; tokens_7d: number;
};
export type SyncRow = { source: string; last_sync: string | null; status: string | null; detail: string | null };
export type IngestStatus = { enabled: boolean; running: boolean; jobs: { id: string; next_run: string | null }[]; state: SyncRow[] };

export type StandardizedHrPoint = {
  month: string; hr: number | null; ci_low: number | null; ci_high: number | null;
  runs: number; local_runs: number; status: "ok" | "provisional" | "insufficient" | "unstable" | "sensitive";
  segment_id?: number;
  reasons: string[]; exploratory_hr: number | null;
};
export type StandardizedHr = {
  reference_minute: number; pace_step_seconds: number; model_version: string; updated_at?: string;
  pace_series: {
    pace_seconds: number; points: StandardizedHrPoint[];
    comparison: { from_month: string; to_month: string; delta: number; ci_low: number; ci_high: number; verdict: "lower" | "higher" | "unclear" } | null;
  }[];
  empty_reason: string | null; caveat: string;
};
export type AnalysisRun = {
  external_id: string; date: string; distance_km: number | null; duration_min: number | null;
  category: "auto" | "normal" | "beast" | "trail" | "run_walk" | "measurement_error";
  exclude: boolean;
};

export type RunningFitnessPoint = {
  date: string; hr: number | null; ci_low: number | null; ci_high: number | null;
  runs: number; local_runs: number; status: string; reasons: string[];
  vo2_eq: number | null; vo2_low: number | null; vo2_high: number | null;
  segment_id?: number; vo2_sensitivity_low?: number | null; vo2_sensitivity_high?: number | null;
};
export type RunningFitnessData = {
  reference_pace_seconds: number; window_days: number; reference_minute: number; method: string;
  points: RunningFitnessPoint[];
  observations: { date: string; external_id: string; hr: number; minutes: number; vo2_eq: number | null; segment_id?: number }[];
  durability?: { date: string; external_id: string; early_hr: number; late_hr: number; delta_bpm: number; segment_id: number }[];
  caveat: string; vo2_status: string; updated_at: string;
  calibration: {
    revision: number; max_hr: number | null; rest_hr: number | null; rest_source: string;
    provisional: boolean; created_at: string; high_hr_source: string;
    sensor_changes: { date: string; label: string }[];
    candidate: { candidate_bpm: number | null; status: string; reason: string } | null;
  };
};
export type RunningFitnessReferenceUpdate =
  | { rest_hr: number; rest_source: string }
  | { max_hr: number }
  | { sensor_change: { date: string; label: string } };

// ---- Rad (Zwift & Indoor, /metrics/cycling) ----
export type CycRide = {
  activity_id: string; type: "virtual_ride" | "indoor_cycling" | string; title: string | null;
  world: string | null; route: string | null; date: string; minutes: number | null; km: number | null;
  elevation_m: number | null; avg_power: number | null; np: number | null; max_power: number | null;
  kj: number | null; cadence: number | null; avg_hr: number | null; max_hr: number | null;
  hr_valid: boolean; eftp: number | null; if: number | null; tss: number | null;
  aerobic_te: number | null; anaerobic_te: number | null; training_load: number | null;
};
export type CycZone = { zone: number; name: string; lo_pct: number; hi_pct: number | null; lo_w: number; hi_w: number | null };
export type CycSummary = {
  rides: number; rides_with_power: number; hours: number; km: number; elevation_m: number; kj: number;
  rides_30d: number; hours_30d: number; tss_7d: number; tss_28d: number; hr_valid_rides: number;
  eftp: number | null; eftp_source: string | null; wkg: number | null; last_ride: CycRide | null;
};
export type CycEftp = {
  value: number | null; source: string | null; wkg: number | null; weight_kg: number | null;
  garmin_ftp: number | null; setting: number | null; window_days: number; factor: number;
  zones: CycZone[]; series: { week: string; eftp: number | null; source: string | null }[]; caveat?: string;
};
export type CycCurve = {
  window_days: number;
  durations: { seconds: number; label: string; recent: number | null; previous: number | null; best: number | null; best_date: string | null }[];
};
export type CycTrend = FitTrend & { bpm_per_month?: number | null; bpm_per_watt?: number | null; delta_bpm?: number | null };
export type CycHrAtPower = {
  ref_power?: number; series?: { date: string; activity_id: string; hr: number; smooth: number }[];
  current?: number | null; caveat?: string; trend?: CycTrend;
};
export type CycEfficiency = {
  series?: { date: string; activity_id: string; ef: number; smooth: number }[]; current?: number | null; rides?: number;
  trend?: FitTrend;
  decoupling?: { date: string; activity_id: string; title: string | null; decoupling_pct: number; vi: number; minutes: number }[];
  caveat?: string;
};
export type CycZones = {
  eftp: number | null; source: string | null; zones: CycZone[];
  weeks: { week: string; seconds: number[]; total: number; rides: number }[]; unzoned_rides: number;
};
export type CycWkgBin = { wkg: number; hr: number; hr_lo: number; hr_hi: number; seconds: number };
export type CycWkgHr = {
  bin: number; window_days: number; eftp: number | null; weight_kg: number | null; wkg_ftp: number | null; hr_max: number;
  power_zones: { zone: number; name: string; lo_wkg: number; hi_wkg: number | null }[];
  hr_zones: { zone: string; name: string; lo_bpm: number; hi_bpm: number }[];
  periods: { key: "recent" | "previous"; label: string; from: string; to: string; rides: number; bins: CycWkgBin[] }[];
  caveat?: string;
};
// ---- Rad-Trainingsplan (/bike-plan) ----
export type BikeStep = { label: string; duration_min: number | null; power_pct: [number, number] | null; cadence: [number | null, number | null] | null; watts: [number, number] | null };
export type BikeExecution =
  | { type: "hr_band"; band: [number | null, number | null]; minutes: number; in_band_pct: number; below_pct: number; above_pct: number; avg_hr: number }
  | { type: "intervals"; shift_s: number; hit_pct: number | null; covered_pct: number; steps: { label: string; target_w: [number, number] | null; avg_w: number | null; in_band_pct: number | null; covered_pct: number }[] }
  | { type: "test"; ftp: number | null }
  | { type: "hr_invalid" };
export type BikeSessionStatus = "done" | "run" | "missed" | "skipped" | "today" | "planned";
export type BikeSession = {
  id: number; date: string; weekday: string; week: number; gym: string | null; title: string; kind: string; optional: boolean;
  steering: string | null; hr: [number | null, number | null] | null; duration_min: number | null; steps: BikeStep[];
  run_alternative: string | null; note: string | null; zwift_workout: string | null; ftp: number; zwo: boolean;
  status: BikeSessionStatus; execution: BikeExecution | null; warnings?: string[];
  ride: { activity_id: string; title: string | null; minutes: number; np: number | null; avg_power: number | null; avg_hr: number | null } | null;
  run: { minutes: number; km: number | null; avg_hr: number | null } | null;
};
export type BikeFtpEntry = { date: string; watts: number; source: "plan" | "ramp" | "manual"; id: string | number | null };
export type BikeWeek = {
  week: number; start: string; end: string; phase: string | null; goal: string | null; current: boolean; sessions: BikeSession[];
  days?: { date: string; weekday: string; gym: string | null; hevy: string | null }[]; warnings?: string[];
};
export type BikeStepInput = { label: string; duration_min: number | null; power_pct: [number, number] | null; cadence: [number | null, number | null] | null };
export type BikePlanOverview = {
  plan: { id: string; name: string; start: string; end: string; imported_at: string } | null;
  today?: string;
  ftp?: BikeFtpEntry & { wkg: number | null; history: BikeFtpEntry[] };
  zones?: { zone: string; from_pct: number; to_pct: number; watts: [number, number] }[];
  hr_targets?: Record<string, unknown> | null;
  weeks?: BikeWeek[];
  progress?: { core: number; core_done: number; optional_done: number; missed: number };
  background?: {
    weekly_template?: { days?: Record<string, string>; rules?: string[]; intensity_distribution?: string } | null;
    in_ride_rules?: { when: string; then: string }[] | null;
    zwift?: { setup?: string[]; z2_routes?: string[]; erg_spiral?: string; [k: string]: unknown } | null;
    expectations?: Record<string, string> | null;
    evidence?: { claim: string; source: string; url?: string }[] | null;
    open_points?: string[] | null;
  };
};
export type BikeCell = { value: number; source: "auto" | "manual" | "plan"; estimated: boolean; note: string | null } | null;
export type BikeCheckpoints = {
  plan: { id: string; name: string } | null;
  today?: string;
  checkpoints?: { key: string; date: string; reached: boolean }[];
  metrics?: { key: string; name: string; unit: string; better: string; target: string | null; how: string | null; derived: boolean; pace: boolean; auto: boolean;
    values: Record<string, BikeCell>; now: BikeCell; delta: number | null; verdict: "up" | "down" | "eq" | null }[];
};
export type CycRideDetail = CycRide & {
  power_curve: { seconds: number; watts: number | null }[];
  zones: (CycZone & { seconds: number | null })[];
  garmin_power_zones: unknown; garmin_hr_zones: unknown; hr_dropout: number | null;
  series: { t: number; power_w?: number | null; cadence_rpm?: number | null; hr_bpm?: number | null; speed_m_s?: number | null; altitude_m?: number | null }[];
};
export type CycWorlds = {
  worlds: { world: string; rides: number; km: number; elevation_m: number; hours: number; last: string;
    routes: { route: string; rides: number; km: number; elevation_m: number; hours: number; last: string }[] }[];
  other_rides: number;
};

export const api = {
  overview: () => get<Overview>("/metrics/overview"),
  // Körper
  bodyWeight: (days = 180) => get<WeightPoint[]>(`/metrics/body/weight?days=${days}`),
  bodyFat: (days = 180) => get<BodyFatPoint[]>(`/metrics/body/bodyfat?days=${days}`),
  bodyFatBand: (days = 180) => get<BodyFatBand>(`/metrics/body/bodyfat-band?days=${days}`),
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
  weather: (index = 0, day = 0) => get<Weather>(`/weather?index=${index}&day=${day}`),
  activityConsistency: (days = 140) => get<Consistency>(`/metrics/activity/consistency?days=${days}`),
  enduranceFitness: (days = 180) => get<EnduranceFitness>(`/metrics/endurance/fitness?days=${days}`),
  activityCompare: (days = 7) => get<WeekCompare>(`/metrics/activity/compare?days=${days}`),
  activityOverview: () => get<ActivityOverview>("/metrics/activity/overview"),
  weeklyReview: () => get<WeeklyReview>("/metrics/activity/weekly-review"),
  sleepOverview: (days = 90) => get<SleepOverview>(`/metrics/sleep/overview?days=${days}`),
  sleepPerformance: (kind: "run" | "strength" = "run", source = "current", days = 180) => get<SleepPerformance>(`/metrics/sleep/performance?kind=${kind}&source=${source}&days=${days}`),
  bodySummary: () => get<BodySummary>("/metrics/body/summary"),
  // Gesundheit (Schritte + Radfahren)
  healthOverview: () => get<HealthOverview>("/metrics/health/overview"),
  healthSteps: (days = 30) => get<StepsTrendPoint[]>(`/metrics/health/steps?days=${days}`),
  healthStepsWeekly: (weeks = 12) => get<StepsWeek[]>(`/metrics/health/steps-weekly?weeks=${weeks}`),
  healthCycling: (weeks = 12) => get<CyclingWeek[]>(`/metrics/health/cycling?weeks=${weeks}`),
  healthCyclingRecent: (limit = 8) => get<CyclingRide[]>(`/metrics/health/cycling-recent?limit=${limit}`),
  // Laufen
  runSummary: () => get<RunSummary>("/metrics/running/summary"),
  runWeekOverview: () => get<RunWeekOverview>("/metrics/running/week-overview"),
  runStandardizedHr: () => get<StandardizedHr>("/metrics/running/standardized-hr"),
  runFitness: () => get<RunningFitnessData>("/metrics/running/fitness"),
  runFitnessReference: (body: RunningFitnessReferenceUpdate) =>
    put<RunningFitnessData>("/metrics/running/fitness-reference", body),
  runAnalysisSessions: () => get<AnalysisRun[]>("/metrics/running/analysis-sessions"),
  runAnalysisUpdate: (id: string, body: Pick<AnalysisRun, "category" | "exclude">) =>
    put<AnalysisRun>(`/metrics/running/analysis-sessions/${encodeURIComponent(id)}`, body),
  runVolume: (weeks = 26) => get<VolPoint[]>(`/metrics/running/volume?weeks=${weeks}`),
  runPace: (weeks = 26) => get<PacePoint[]>(`/metrics/running/pace?weeks=${weeks}`),
  runPaceDetail: () => get<PaceDetail>("/metrics/running/pace-detail"),
  runVo2: (days = 365) => get<Vo2Point[]>(`/metrics/running/vo2?days=${days}`),
  runHeartRate: (weeks = 26) => get<HrPoint[]>(`/metrics/running/heart-rate?weeks=${weeks}`),
  runPaceAtHr: () => get<PaceAtHr>("/metrics/running/pace-at-hr"),
  runEasyHr: () => get<EasyHr>("/metrics/running/easy-hr"),
  runTrimp: (weeks = 26) => get<Trimp>(`/metrics/running/trimp?weeks=${weeks}`),
  runPaceByZone: () => get<PaceByZone>("/metrics/running/pace-by-zone"),
  cycSummary: () => get<CycSummary>("/metrics/cycling/summary"),
  cycPowerCurve: () => get<CycCurve>("/metrics/cycling/power-curve"),
  cycEftp: (weeks = 26) => get<CycEftp>(`/metrics/cycling/eftp?weeks=${weeks}`),
  cycHrAtPower: () => get<CycHrAtPower>("/metrics/cycling/hr-at-power"),
  cycEfficiency: () => get<CycEfficiency>("/metrics/cycling/efficiency"),
  bikePlan: () => get<BikePlanOverview>("/bike-plan"),
  bikePlanImport: async (file: File): Promise<{ id: string; name: string; weeks: number; sessions: number }> => {
    const form = new FormData();
    form.append("file", file);
    const r = await fetch(`${BASE}/bike-plan`, { method: "POST", body: form });
    if (!r.ok) {
      const detail = await r.json().then((j) => j?.detail).catch(() => null);
      throw new Error(typeof detail === "string" ? detail : `Import fehlgeschlagen (${r.status})`);
    }
    return r.json();
  },
  bikePlanDelete: async (id: string) => {
    const r = await fetch(`${BASE}/bike-plan/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`/bike-plan/${id} → ${r.status}`);
  },
  bikePlanFtp: (watts: number) => post<NonNullable<BikePlanOverview["ftp"]>>("/bike-plan/ftp", { watts }),
  bikePlanFtpDelete: async (id: number) => {
    const r = await fetch(`${BASE}/bike-plan/ftp/${id}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`/bike-plan/ftp/${id} → ${r.status}`);
  },
  bikePlanSessionUpdate: (id: number, changes: Record<string, unknown>) => send<BikePlanOverview>("PUT", `/bike-plan/session/${id}`, changes),
  bikePlanSessionCreate: (day: string, copyFrom?: number | null) => send<BikePlanOverview>("POST", "/bike-plan/session", { day, copy_from: copyFrom ?? null }),
  bikePlanSessionDelete: (id: number) => send<BikePlanOverview>("DELETE", `/bike-plan/session/${id}`),
  bikePlanGym: (day: string, label: string | null) => send<BikePlanOverview>("PUT", "/bike-plan/gym", { day, label }),
  bikePlanCheckpoints: () => get<BikeCheckpoints>("/bike-plan/checkpoints"),
  bikePlanCheckpointSet: (body: { checkpoint: string; key: string; value: number | null; estimated?: boolean }) =>
    put<BikeCheckpoints>("/bike-plan/checkpoints", body),
  cycWkgHr: () => get<CycWkgHr>("/metrics/cycling/wkg-hr"),
  cycZones: (weeks = 12) => get<CycZones>(`/metrics/cycling/zones?weeks=${weeks}`),
  cycRides: (limit = 20) => get<CycRide[]>(`/metrics/cycling/rides?limit=${limit}`),
  cycRide: (id: string) => get<CycRideDetail>(`/metrics/cycling/ride/${encodeURIComponent(id)}`),
  cycWorlds: () => get<CycWorlds>("/metrics/cycling/worlds"),
  runEf: () => get<EfTrend>("/metrics/running/ef"),
  runBestEfforts: (top = 3) => get<BestEfforts>(`/metrics/running/best-efforts?top=${top}`),
  runAchievements: () => get<Achievements>("/metrics/running/achievements"),
  hero: () => get<Hero>("/hero"),
  heroClaim: (week: string, slot: number) => post<{ item: HeroItem }>("/hero/vault/claim", { week, slot }),
  heroEquip: (itemId: string) => post<{ item: HeroItem }>("/hero/equip", { item_id: itemId }),
  heroUnequip: (slot: string) => post<{ slot: string }>("/hero/unequip", { slot }),
  heroEquipBest: () => post<{ equipped: Record<string, string> }>("/hero/equip-best"),
  heroSpec: (spec: string | null) => post<{ spec: string | null }>("/hero/spec", { spec }),
  heroTalent: (row: number, choice: string | null) => post<{ row: number; choice: string | null }>("/hero/talent", { row, choice }),
  heroTitle: (key: string | null) => post<{ key: string | null }>("/hero/title", { key }),
  heroMount: (key: string | null) => post<{ key: string | null }>("/hero/mount", { key }),
  heroSell: (itemId: string) => post<{ gold: number }>("/hero/sell", { item_id: itemId }),
  heroBuy: (kind: "listing" | "potion", ref: string) => post<{ kind: string; price: number }>("/hero/buy", { kind, ref }),
  heroDrink: (key: string) => post<{ key: string }>("/hero/drink", { key }),
  heroWorldTiles: (x0: number, y0: number, x1: number, y1: number, px: number) =>
    get<{ z: number | null; tiles: HeroTile[] }>(`/hero/world/tiles?x0=${Math.round(x0)}&y0=${Math.round(y0)}&x1=${Math.round(x1)}&y1=${Math.round(y1)}&px=${Math.round(px)}`),
  heroLivePost: (token: string, session: string, points: { ts: number; lat: number; lon: number; acc: number }[]) =>
    live<{ session: string; accepted: number; rejected: number }>(token, "POST", "/hero/live", { session, points }),
  heroLiveState: (token: string, session: string) =>
    live<HeroLiveState>(token, "GET", `/hero/live/state?session=${encodeURIComponent(session)}`),
  heroLiveTarget: (token: string, session: string, target: { kind: "poi" | "dungeon"; id: string } | null) =>
    live<{ session: string }>(token, "POST", "/hero/live/target", { session, ...(target ?? {}) }),
  heroKeystonePreview: (token: string, dungeon: string) =>
    live<HeroKeystonePreview>(token, "GET", `/hero/live/keystone?dungeon=${encodeURIComponent(dungeon)}`),
  heroKeystoneActivate: (token: string, session: string, dungeon: string, level: number, affixes: string[]) =>
    live<{ session: string; dungeon: string; level: number; time_limit_s: number }>(token, "POST", "/hero/live/keystone", { session, dungeon, level, affixes }),
  heroKeystoneAbort: (token: string, session: string) =>
    live<{ session: string; aborted: boolean }>(token, "POST", "/hero/live/keystone/abort", { session }),
  heroEventDecline: (token: string, session: string) =>
    live<{ session: string; declined: boolean }>(token, "POST", "/hero/live/event/decline", { session }),
  heroTileUrl: (key: string) => `${BASE}/hero/world/tile/${key}`,
  heroOwnRoutes: () => get<HeroOwnRoute[]>("/hero/world/own"),
  // Fehler tragen die Meldung des Servers (z. B. „Die Strecke ist zu kurz …“).
  heroOwnImport: async (file: File, mode: "dungeon" | "track"): Promise<HeroOwnRoute> => {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    const r = await fetch(`${BASE}/hero/world/own`, { method: "POST", body: form });
    if (!r.ok) {
      const detail = await r.json().then((j) => j?.detail).catch(() => null);
      throw new Error(typeof detail === "string" ? detail : `Import fehlgeschlagen (${r.status})`);
    }
    return r.json() as Promise<HeroOwnRoute>;
  },
  heroOwnDelete: async (id: string) => {
    const r = await fetch(`${BASE}/hero/world/own/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`/hero/world/own/${id} → ${r.status}`);
    return r.json();
  },
  heroSaga: () => get<{ saga: HeroSaga | null; week: string }>("/hero/saga"),
  heroWriteSaga: () => post<{ saga: HeroSaga }>("/hero/saga"),
  heroDisenchant: (itemId: string) => post<{ dust: number }>("/hero/disenchant", { item_id: itemId }),
  heroUpgrade: (itemId: string) => post<{ item: HeroItem }>("/hero/upgrade", { item_id: itemId }),
  healthRestingHr: (days = 365) => get<RestingHr>(`/metrics/health/resting-hr?days=${days}`),
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
  strengthPlan: () => get<NextTraining>("/metrics/strength/plan"),
  strengthVolume: () => get<WeeklyVolume>("/metrics/strength/volume"),
  writeHevyRoutines: () => post<Record<string, unknown>>("/ingest/hevy-routines"),
  // Coach
  coachReports: (limit = 10) => get<Report[]>(`/coach/reports?limit=${limit}`),
  coachDaily: () => post<Report>("/coach/daily"),
  coachWeekly: () => post<Report>("/coach/weekly"),
  coachChat: (message: string, history?: { role: string; content: string }[]) =>
    post<Report>("/coach/chat", { message, history }),
  coachAsk: (message: string, history?: { role: string; content: string }[]) =>
    post<Report>("/coach/ask", { message, history }),
  coachStats: () => get<CoachStats>("/coach/stats"),
  coachBriefingToday: () => get<BriefingToday>("/coach/briefing/today"),
  coachWeeklyAuto: () => get<WeeklyAutoCurrent>("/coach/weekly-auto/current"),
  generateCoachImage: (prompt: string) => post<CoachImage>("/coach/images", { prompt }),
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
  coachProfileGet: () => get<CoachProfile>("/settings/coach"),
  coachProfileUpdate: (body: CoachProfileUpdate) => put<CoachProfile>("/settings/coach", body),
  settingsGet: () => get<AppSettings>("/settings"),
  settingsUpdate: (body: SettingsUpdate) => put<AppSettings>("/settings", body),
};
