"use client";

import { useEffect, useState } from "react";
import { api, type WeightPhasePreset, type WeightRate as Rate } from "@/lib/api";
import { de, dm } from "@/lib/format";

const WEEKS_PER_MONTH = 30.44 / 7;
const signed = (value: number, digits: number) => `${value > 0 ? "+" : value < 0 ? "−" : "±"}${de(Math.abs(value), digits)}`;

/** Korridor lesbar: Cut je Woche, Erhalt/Aufbau je Monat (dort sind die Richtwerte so formuliert). */
export function corridorText(p: WeightPhasePreset, weight?: number | null) {
  const perMonth = p.kind !== "cut";
  const [lo, hi] = [p.rate_min_pct, p.rate_max_pct].map((r) => perMonth ? r * WEEKS_PER_MONTH : r);
  const unit = perMonth ? "Monat" : "Woche";
  const pct = p.kind === "maintain" ? `±${de(hi, 2)} %/${unit}` : `${signed(lo, 2)} bis ${signed(hi, 2)} %/${unit}`;
  if (!weight) return pct;
  const kg = [lo, hi].map((r) => r / 100 * weight);
  return `${pct} (${p.kind === "maintain" ? `±${de(kg[1], 2)}` : `${signed(kg[0], 2)} bis ${signed(kg[1], 2)}`} kg)`;
}

const tone = (r: Rate) => r.verdict === "im" ? "text-[var(--color-good)]"
  : (r.verdict === "below" || r.verdict === "above") && r.certain ? "text-[var(--color-bad)]" : "text-muted";

export function WeightRate({ onChange }: { onChange: () => void }) {
  const [rate, setRate] = useState<Rate | null>(null);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState(false);
  const [preset, setPreset] = useState("maintain");
  const [start, setStart] = useState(() => new Date().toLocaleDateString("sv-SE"));
  const [error, setError] = useState<string | null>(null);
  const load = () => api.bodyWeightRate().then((value) => { setRate(value); setFailed(false); }).catch(() => setFailed(true));
  useEffect(() => { load(); }, []);
  if (failed) return <p className="mt-3 text-xs text-muted">Tempo konnte nicht geladen werden.</p>;
  if (!rate) return <p role="status" className="mt-3 text-xs text-muted">Tempo wird geladen …</p>;
  const save = async () => {
    setError(null);
    try { await api.setWeightPhase(start, preset); setEditing(false); await load(); onChange(); }
    catch (e) { setError(e instanceof Error ? e.message : "Speichern fehlgeschlagen"); }
  };
  const remove = async (id: number) => {
    try { await api.deleteWeightPhase(id); await load(); onChange(); } catch { setError("Löschen fehlgeschlagen"); }
  };
  const r = rate.rate, phase = rate.phase;
  return <div className="mt-4 rounded-lg border border-line p-3 text-sm">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <p className="font-semibold">{phase ? phase.name : "Keine Phase gewählt"}
        {phase && <span className="ml-2 text-xs font-normal text-muted">seit {dm(phase.start)} · Ziel {corridorText(phase, r?.weight)}</span>}</p>
      <button className="text-xs text-accent underline underline-offset-4" onClick={() => setEditing(!editing)}>{phase ? "Phase wechseln" : "Phase wählen"}</button>
    </div>
    {r ? <p className="mt-2">
      Tempo der letzten {rate.span_days + 1} Tage: <b>{signed(r.kg_per_week, 2)} kg/Woche</b>
      <span className="text-muted"> · {signed(r.pct_per_week, 2)} %/Woche ({signed(r.pct_per_month, 1)} %/Monat) · ±{de(r.ci_kg, 2)} kg Unsicherheit</span>
    </p> : null}
    <p className={`mt-1 font-semibold ${tone(rate)}`}>{rate.verdict === "im" ? "✓ " : ""}{rate.label}
      {rate.kcal_per_day != null && <span className="font-normal text-muted"> · Richtung Korridormitte etwa {signed(rate.kcal_per_day, 0)} kcal/Tag</span>}</p>
    {rate.verdict === "wenig_daten" && <p className="mt-1 text-xs text-muted">{rate.n} Wiegungen seit {dm(rate.from_date)}.</p>}
    {editing && <div className="mt-3 grid gap-2 border-t border-line pt-3 sm:grid-cols-[1fr_auto_auto] sm:items-end">
      <label className="text-xs text-muted">Phase
        <select className="mt-1 block w-full rounded border border-line bg-surface px-2 py-1.5 text-base text-ink sm:text-sm" value={preset} onChange={(e) => setPreset(e.target.value)}>
          {rate.presets.map((p) => <option key={p.preset} value={p.preset}>{p.name} · {corridorText(p)}</option>)}
        </select>
      </label>
      <label className="text-xs text-muted">ab
        <input type="date" className="mt-1 block rounded border border-line bg-surface px-2 py-1.5 text-base text-ink sm:text-sm" value={start} onChange={(e) => setStart(e.target.value)} />
      </label>
      <button className="rounded bg-accent px-3 py-2 text-sm font-semibold text-white" onClick={save}>Speichern</button>
      {error && <p className="text-xs text-[var(--color-bad)] sm:col-span-3">{error}</p>}
      {rate.phases.length > 0 && <ul className="text-xs text-muted sm:col-span-3">
        {[...rate.phases].reverse().map((p) => <li key={p.id} className="flex justify-between gap-2 py-0.5">
          <span>{dm(p.start)}{p.start.slice(0, 4)}{p.end ? `–${dm(p.end)}` : " – heute"} · {p.name}</span>
          <button className="underline underline-offset-4" onClick={() => remove(p.id)}>entfernen</button>
        </li>)}
      </ul>}
    </div>}
    <details className="mt-3 text-xs text-muted">
      <summary className="cursor-pointer">So liest du den Korridor</summary>
      <ul className="mt-2 list-disc space-y-1 pl-4">
        <li>Das helle Band im Diagramm beginnt am Startgewicht der Phase und öffnet sich mit dem Mindest- und Höchsttempo.</li>
        <li>Wiege dich morgens nach der Toilette, vor Essen und Trinken. Das Tempo kommt aus allen Einzelwiegungen der letzten 4 Wochen, nicht aus einzelnen Tagen.</li>
        <li>Dein Gewicht schwankt von Tag zu Tag um etwa ±0,4 kg (Wasser, Salz, Kohlenhydrate, Darm). Urteile erst nach 3–4 Wochen; „noch unsicher“ heißt: abwarten.</li>
        <li>Richtwerte: Cut 0,5–1 %/Woche (Helms 2014), etwa 0,7 %/Woche erhielt mehr Muskel als 1 % (Garthe 2011). Aufbau: Anfänger 1–2 %/Monat, Fortgeschrittene 0,5–1 %, Erfahrene 0,25–0,5 % — mehr Überschuss bringt vor allem Fett (Helms 2023). Expertenkonsens, kein Gesetz.</li>
        <li>Der Kalorienhinweis rechnet 7.700 kcal je kg und ist nur ein Startwert; danach wieder 2–3 Wochen beobachten.</li>
      </ul>
    </details>
  </div>;
}
