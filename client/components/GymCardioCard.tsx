"use client";

import { useEffect, useState } from "react";
import { api, type GymCardio, type GymCardioEntry } from "@/lib/api";
import { Card } from "@/components/ui";
import { de, de0, dm } from "@/lib/format";

const SOURCE: Record<string, string> = { custom: "geändert", note: "aus Notiz", default: "Standard" };
const KIND: Record<string, string> = { bike: "zählt zu Rad", stairs: "zählt zu Gym" };

function Row({ e, max, onSave }: { e: GymCardioEntry; max: number; onSave: (pct: number | null) => Promise<void> }) {
  const [value, setValue] = useState(e.incline_pct === null ? "" : String(e.incline_pct));
  const [busy, setBusy] = useState(false);
  useEffect(() => setValue(e.incline_pct === null ? "" : String(e.incline_pct)), [e.incline_pct]);
  const pct = parseFloat(value.replace(",", "."));
  const valid = !Number.isNaN(pct) && pct >= 0 && pct <= max;
  const dirty = valid && pct !== e.incline_pct;
  const save = (next: number | null) => { setBusy(true); onSave(next).finally(() => setBusy(false)); };
  const minutes = e.duration_s ? e.duration_s / 60 : null;
  return <li className="border-t border-line py-2 text-sm first:border-t-0">
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <span className="min-w-0">
        <span className="font-medium">{dm(e.date)} · {e.started_at.slice(11, 16)}</span>
        <span className="text-muted"> · {e.exercise}{minutes ? ` · ${de0(minutes)} min` : ""}{e.distance_m ? ` · ${de(e.distance_m / 1000, 2)} km` : ""}{e.speed_kmh ? ` · ${de(e.speed_kmh, 1)} km/h` : ""}</span>
        {e.duration_fixed && <span className="ml-2 rounded bg-line px-1.5 py-0.5 text-[11px] text-muted" title="In Hevy als Sekunden eingetragen, das Tempo wäre unmöglich – als Minuten gelesen">Dauer als Minuten gelesen</span>}
      </span>
      <span className="text-xs text-muted">{e.kcal !== null ? `≈ ${de0(e.kcal)} kcal` : "zu wenig Daten – zählt als Krafttraining"}{e.kcal_flat !== null && e.kcal !== null && e.kcal > e.kcal_flat ? ` · Steigung +${de0(e.kcal - e.kcal_flat)}` : ""}</span>
    </div>
    {e.kind === "treadmill" ? <form className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted" onSubmit={(ev) => { ev.preventDefault(); if (dirty) save(pct); }}>
      <label className="flex items-center gap-1">Steigung
        <input type="number" inputMode="decimal" min={0} max={max} step={0.5} value={value} onChange={(ev) => setValue(ev.target.value)}
          className="w-16 rounded border border-line bg-surface px-1.5 py-0.5 text-base sm:text-sm" aria-label={`Steigung am ${dm(e.date)}`} /> %
      </label>
      {e.incline_source && <span className="rounded bg-line px-1.5 py-0.5 text-[11px]">{SOURCE[e.incline_source]}</span>}
      {dirty && <button type="submit" disabled={busy} className="rounded border border-accent px-2 py-0.5 text-accent">Speichern</button>}
      {e.incline_source === "custom" && !dirty && <button type="button" disabled={busy} onClick={() => save(null)} className="rounded border border-line px-2 py-0.5">Zurücksetzen</button>}
      {e.mode === "run" && <span>gelaufen (ab 8 km/h)</span>}
    </form> : <p className="mt-1 text-xs text-muted">{KIND[e.kind]}</p>}
  </li>;
}

export function GymCardioCard({ onChange }: { onChange?: () => void }) {
  const [data, setData] = useState<GymCardio | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const load = () => api.gymCardio(365).then(setData).catch(() => setError("Daten konnten nicht geladen werden."));
  useEffect(() => { load(); }, []);
  if (error && !data) return <Card className="mt-4"><h2 className="text-sm font-semibold">Laufband im Gym</h2><p className="mt-3 text-xs text-muted">{error}</p></Card>;
  if (!data || !data.entries.length) return null;
  const save = (key: string) => (pct: number | null) => api.gymCardioIncline(key, pct)
    .then(() => { setError(null); onChange?.(); return load(); })
    .catch((err: Error) => setError(err.message));
  const shown = all ? data.entries : data.entries.slice(0, 6);
  return <Card className="mt-4">
    <h2 className="text-sm font-semibold">Laufband im Gym · aus Hevy</h2>
    <p className="mt-1 text-xs text-muted">Cardio-Sätze aus deinen Workouts, letzte 12 Monate. Hevy kennt keine Steigung: Milon nimmt eine Zahl mit % aus der Übungsnotiz, sonst {de(data.default_incline_pct, 1)} % (Einstellungen). Hier kannst du sie je Eintrag ändern.</p>
    {error && <p className="mt-2 text-xs text-bad" role="alert">{error}</p>}
    <ul className="mt-3">{shown.map((e) => <Row key={e.key} e={e} max={data.incline_max} onSave={save(e.key)} />)}</ul>
    {data.entries.length > 6 && <button type="button" onClick={() => setAll(!all)} className="mt-2 text-xs text-accent">{all ? "Weniger anzeigen" : `Alle ${data.entries.length} anzeigen`}</button>}
    <p className="mt-3 text-[11px] text-muted">kcal = Aktivkalorien ohne Grundumsatz nach ACSM (Gehen bzw. ab 8 km/h Laufen, inkl. Steigung) mit deinem 7-Tage-Gewicht. Diese Minuten fallen aus der Krafttraining-Pauschale, die Schritte (Strecke ÷ Schrittlänge) aus der Alltagsbewegung – die Uhr hat sie schon gezählt.</p>
  </Card>;
}
