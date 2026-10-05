export type SyncItem = { id: string; date: string; href: string };
export const SYNC_KINDS = ["runs", "nights", "workouts", "weights", "nutrition"] as const;
export type SyncInventory = Record<(typeof SYNC_KINDS)[number], SyncItem[]>;
export type SyncFeedback = SyncInventory & { createdAt: number };
export const FEEDBACK_LIFETIME = 120_000;
const STORAGE = "milon:sync-feedback";
const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");

function validInventory(value: unknown): value is SyncInventory {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return SYNC_KINDS.every(kind => Array.isArray(record[kind]) && record[kind].every((item: unknown) => {
    if (!item || typeof item !== "object") return false;
    const row = item as Record<string, unknown>;
    return typeof row.id === "string" && typeof row.date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(row.date)
      && typeof row.href === "string" && /^\/(laufen(?:\/\d+)?|gesundheit(?:\?night=\d{4}-\d{2}-\d{2})?|kraft|koerper|ernaehrung)$/.test(row.href);
  }));
}

export async function captureSyncInventory(): Promise<SyncInventory | null> {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 4000);
  try {
    const response = await fetch(`${BASE}/ingest/inventory`, { cache: "no-store", signal: controller.signal });
    if (!response.ok) return null;
    const value: unknown = await response.json();
    return validInventory(value) ? value : null;
  } catch { return null; }
  finally { clearTimeout(timer); }
}

export function addedSyncItems(before: SyncInventory, after: SyncInventory, now = Date.now()): SyncFeedback {
  return { createdAt: now, ...Object.fromEntries(SYNC_KINDS.map(kind => {
    const previous = new Set(before[kind].map(item => item.id));
    const unique = new Map(after[kind].filter(item => !previous.has(item.id)).map(item => [item.id, item]));
    return [kind, [...unique.values()].sort((a, b) => b.date.localeCompare(a.date))];
  })) } as SyncFeedback;
}

export function syncFeedbackText(feedback: SyncFeedback): string {
  const labels = { runs: ["Lauf", "Läufe"], nights: ["Nacht", "Nächte"], workouts: ["Gym-Einheit", "Gym-Einheiten"], weights: ["Wiegetag", "Wiegetage"], nutrition: ["Ernährungstag", "Ernährungstage"] };
  const parts = SYNC_KINDS.flatMap(kind => feedback[kind].length ? [`${feedback[kind].length} ${labels[kind][Number(feedback[kind].length !== 1)]}`] : []);
  return parts.length ? `${parts.join(" · ")} ergänzt` : "Daten aktualisiert · keine neuen Einträge";
}

export function readSyncFeedback(): SyncFeedback | null {
  if (typeof window === "undefined") return null;
  try {
    const value = JSON.parse(sessionStorage.getItem(STORAGE) || "null");
    if (!value || !Number.isFinite(value.createdAt) || Date.now() - value.createdAt >= FEEDBACK_LIFETIME
        || value.createdAt > Date.now() || !validInventory(value)) return null;
    return value as SyncFeedback;
  } catch { return null; }
}

export async function finishManualSync(before: SyncInventory | null, source = "manual-sync"): Promise<string> {
  const after = before ? await captureSyncInventory() : null;
  const feedback = before && after ? addedSyncItems(before, after) : null;
  if (feedback) {
    try { sessionStorage.setItem(STORAGE, JSON.stringify(feedback)); } catch { /* Storage is optional. */ }
  } else { try { sessionStorage.removeItem(STORAGE); } catch { /* Storage is optional. */ } }
  window.dispatchEvent(new CustomEvent("milon:sync-feedback", { detail: feedback }));
  window.dispatchEvent(new CustomEvent("milon:data-refresh", { detail: { source } }));
  return feedback ? syncFeedbackText(feedback) : "Daten aktualisiert.";
}
