"use client";

import { useEffect, useState } from "react";
import { api, type WalkpadOverview, type WalkpadSessionRow } from "@/lib/api";
import { Card, StatRow } from "@/components/ui";
import { Bars } from "@/components/charts";
import { de, de0, dm } from "@/lib/format";

const GARMIN: Record<string, string> = { uploaded: "in Garmin Connect", duplicate: "in Garmin Connect", error: "Upload fehlgeschlagen", off: "" };
const INPUT = "w-full rounded border border-line bg-surface px-2 py-1 text-base sm:text-sm";

function SessionRow({ s, onIncline, onDelete }: { s: WalkpadSessionRow; onIncline: (pct: number) => void; onDelete: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const time = s.started_at.slice(11, 16);
  const garmin = s.garmin_status === null ? "Upload ausstehend" : GARMIN[s.garmin_status] ?? "";
  return <li className="border-t border-line py-2 text-sm first:border-t-0">
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <span className="min-w-0">
        <span className="font-medium">{dm(s.date)} · {time}</span>
        <span className="text-muted"> · {de0(s.minutes)} min · {de(s.distance_km, 2)} km · {de(s.avg_speed_kmh, 1)} km/h</span>
        {s.source === "manual" && <span className="ml-2 rounded bg-line px-1.5 py-0.5 text-[11px] text-muted">manuell</span>}
      </span>
      <span className="flex items-center gap-2 text-xs text-muted">
        <span title={s.steps_provisional ? "Uhr-Schritte im Zeitfenster noch nicht abgeglichen" : `Uhr zählte ${de0(s.watch_steps)} davon schon`}>
          {de0(s.steps)} Schritte{s.steps_provisional ? " (vorläufig)" : ` · +${de0(s.extra_steps)}`}
        </span>
        <button type="button" className="rounded border border-line px-1.5 py-0.5" title="Steigung: Klappe oben (6 %) oder weggeklappt (0 %)"
          onClick={() => onIncline(s.incline_pct > 0 ? 0 : 6)}>{de0(s.incline_pct)} %</button>
        {garmin && <span>{garmin}</span>}
        {s.source === "manual" && (confirm
          ? <button type="button" className="text-bad underline underline-offset-4" onClick={onDelete}>Sicher löschen?</button>
          : <button type="button" aria-label="Walk löschen" className="px-1 hover:text-bad" onClick={() => setConfirm(true)}>✕</button>)}
      </span>
    </div>
    <p className="mt-0.5 text-xs text-muted">
      {s.kcal !== null ? <>≈ {de0(s.kcal)} kcal{s.kcal_incline ? <> · davon Steigung +{de0(s.kcal_incline)} kcal (+{de0(100 * s.kcal_incline / (s.kcal_flat || 1))} % ggü. Ebene)</> : null}</> : "kcal: kein Gewicht erfasst"}
      {s.elevation_m ? ` · ${de0(s.elevation_m)} Hm` : ""}
      {s.kcal_pad !== null ? ` · Pad: ${de0(s.kcal_pad)} kcal` : ""}
    </p>
  </li>;
}

function ManualForm({ incline, onSaved }: { incline: number; onSaved: () => void }) {
  const [start, setStart] = useState("");
  const [minutes, setMinutes] = useState("");
  const [speed, setSpeed] = useState("3.5");
  const [up, setUp] = useState(incline > 0);
  const [msg, setMsg] = useState<string | null>(null);
  const save = () => {
    const m = parseFloat(minutes.replace(",", ".")), v = parseFloat(speed.replace(",", "."));
    if (!start || Number.isNaN(m) || Number.isNaN(v)) { setMsg("Start, Dauer und Tempo angeben."); return; }
    api.walkpadManual({ started_at: start, minutes: m, speed_kmh: v, incline_pct: up ? 6 : 0 })
      .then(() => { setMsg(null); setStart(""); setMinutes(""); onSaved(); })
      .catch((e) => setMsg(String(e.message ?? e)));
  };
  return <details className="mt-3 text-sm">
    <summary className="cursor-pointer text-xs text-muted">+ Walk nachtragen</summary>
    <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
      <label className="col-span-2 sm:col-span-1"><span className="mb-1 block text-[11px] text-muted">Start</span>
        <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} className={INPUT} /></label>
      <label><span className="mb-1 block text-[11px] text-muted">Dauer (min)</span>
        <input type="number" inputMode="numeric" min={2} value={minutes} onChange={(e) => setMinutes(e.target.value)} className={INPUT} /></label>
      <label><span className="mb-1 block text-[11px] text-muted">Tempo (km/h)</span>
        <input type="number" inputMode="decimal" min={1} max={6} step={0.1} value={speed} onChange={(e) => setSpeed(e.target.value)} className={INPUT} /></label>
      <label className="flex items-center gap-2 self-end pb-1"><input type="checkbox" checked={up} onChange={(e) => setUp(e.target.checked)} />Steigung 6 %</label>
    </div>
    <div className="mt-2 flex items-center gap-3">
      <button type="button" onClick={save} className="rounded border border-line px-3 py-1">Eintragen</button>
      {msg && <span className="text-xs text-bad">{msg}</span>}
    </div>
  </details>;
}

export function WalkpadCard() {
  const [data, setData] = useState<WalkpadOverview | null>(null);
  const [error, setError] = useState(false);
  const load = () => api.walkpad(12).then(setData).catch(() => setError(true));
  useEffect(() => { load(); }, []);
  if (error) return <Card className="mt-4"><h2 className="text-sm font-semibold">Laufband</h2><p className="mt-3 text-xs text-muted">Daten konnten nicht geladen werden.</p></Card>;
  if (!data) return null;
  if (!data.total_sessions) return <Card className="mt-4">
    <h2 className="text-sm font-semibold">Laufband</h2>
    <p className="mt-2 text-xs text-muted">{data.recorder_enabled
      ? "Noch kein Walk erfasst – der Recorder auf dem PC schickt jede Session nach dem Stopp."
      : "Recorder nicht eingerichtet (WALKPAD_TOKEN in server/.env + tools/walkpad)."}</p>
    <ManualForm incline={data.incline_pct} onSaved={load} />
  </Card>;
  const incline = (id: string, pct: number) => api.walkpadIncline(id, pct).then(load).catch(() => setError(true));
  const remove = (id: string) => api.walkpadDelete(id).then(load).catch(() => setError(true));
  const w = data.week;
  return <Card className="mt-4">
    <h2 className="text-sm font-semibold">Laufband · diese Woche</h2>
    <p className="mt-3 font-display text-2xl font-extrabold">{de0(w.minutes)} <span className="text-sm font-normal text-muted">min</span> {de(w.km, 1)} <span className="text-sm font-normal text-muted">km</span></p>
    <StatRow items={[
      ["Heute", `${de0(data.today.minutes)} min · ${de0(data.today.steps)} Schritte`],
      ["Schritte (Woche)", `${de0(w.steps)} · +${de0(w.extra_steps)} zur Uhr`],
      ["Energie", `≈ ${de0(w.kcal)} kcal${w.kcal_incline ? ` · Steigung +${de0(w.kcal_incline)}` : ""}`],
      ...(w.elevation_m ? [["Höhenmeter", `${de0(w.elevation_m)} m`] as [string, string]] : []),
    ]} />
    <div className="mt-4">
      <Bars unit="min" data={data.weeks.map((x) => ({ label: dm(x.week), value: x.minutes }))} height={140} />
    </div>
    <ul className="mt-3">{data.recent.map((s) => <SessionRow key={s.id} s={s} onIncline={(pct) => incline(s.id, pct)} onDelete={() => remove(s.id)} />)}</ul>
    <ManualForm incline={data.incline_pct} onSaved={load} />
    <p className="mt-3 text-xs text-muted">
      Schritte geschätzt aus Distanz ÷ {de(data.stride_m, 2)} m Schrittlänge. Zu den Tagesschritten zählt nur, was die Uhr im selben Zeitfenster nicht schon gezählt hat.
      {" "}kcal nach der ACSM-Gehformel mit deinem 7-Tage-Gewicht (inkl. Steigung); der Pad-Wert rechnet ohne Steigung.
      {data.garmin_upload ? " Jeder Walk geht als „Gehen (Indoor)“ zu Garmin Connect – Garmins Tagesschritte ändert das nicht." : ""}
    </p>
  </Card>;
}
