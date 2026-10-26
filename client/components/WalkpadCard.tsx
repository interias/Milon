"use client";

import { useEffect, useState } from "react";
import { api, type WalkpadOverview, type WalkpadSessionRow } from "@/lib/api";
import { Card, StatRow } from "@/components/ui";
import { Bars } from "@/components/charts";
import { de, de0, dm } from "@/lib/format";

const GARMIN: Record<string, string> = { uploaded: "in Garmin Connect", duplicate: "in Garmin Connect", error: "Upload fehlgeschlagen", off: "" };

function SessionRow({ s, onIncline }: { s: WalkpadSessionRow; onIncline: (pct: number) => void }) {
  const time = s.started_at.slice(11, 16);
  const garmin = s.garmin_status === null ? "Upload ausstehend" : GARMIN[s.garmin_status] ?? "";
  return <li className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-t border-line py-2 text-sm first:border-t-0">
    <span className="min-w-0">
      <span className="font-medium">{dm(s.date)} · {time}</span>
      <span className="text-muted"> · {de0(s.minutes)} min · {de(s.distance_km, 2)} km · {de(s.avg_speed_kmh, 1)} km/h</span>
    </span>
    <span className="flex items-center gap-2 text-xs text-muted">
      <span title={s.steps_provisional ? "Uhr-Schritte im Zeitfenster noch nicht abgeglichen" : `Uhr zählte ${de0(s.watch_steps)} davon schon`}>
        {de0(s.steps)} Schritte{s.steps_provisional ? " (vorläufig)" : ` · +${de0(s.extra_steps)}`}
      </span>
      <button type="button" className="rounded border border-line px-1.5 py-0.5" title="Steigung umschalten (am Pad manuell eingestellt)"
        onClick={() => onIncline(s.incline_pct > 0 ? 0 : 6)}>{de0(s.incline_pct)} %</button>
      {garmin && <span>{garmin}</span>}
    </span>
  </li>;
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
  </Card>;
  const incline = (id: string, pct: number) => api.walkpadIncline(id, pct).then(load).catch(() => setError(true));
  const w = data.week;
  return <Card className="mt-4">
    <h2 className="text-sm font-semibold">Laufband · diese Woche</h2>
    <p className="mt-3 font-display text-2xl font-extrabold">{de0(w.minutes)} <span className="text-sm font-normal text-muted">min</span> {de(w.km, 1)} <span className="text-sm font-normal text-muted">km</span></p>
    <StatRow items={[
      ["Heute", `${de0(data.today.minutes)} min · ${de0(data.today.steps)} Schritte`],
      ["Schritte (Woche)", `${de0(w.steps)} · +${de0(w.extra_steps)} zur Uhr`],
      ["Energie", `${de0(w.kcal)} kcal`],
      ...(w.elevation_m ? [["Höhenmeter", `${de0(w.elevation_m)} m`] as [string, string]] : []),
    ]} />
    <div className="mt-4">
      <Bars unit="min" data={data.weeks.map((x) => ({ label: dm(x.week), value: x.minutes }))} height={140} />
    </div>
    <ul className="mt-3">{data.recent.map((s) => <SessionRow key={s.id} s={s} onIncline={(pct) => incline(s.id, pct)} />)}</ul>
    <p className="mt-3 text-xs text-muted">
      Schritte geschätzt aus Distanz ÷ {de(data.stride_m, 2)} m Schrittlänge. Zu den Tagesschritten zählt nur, was die Uhr im selben Zeitfenster nicht schon gezählt hat.
      {data.garmin_upload ? " Jeder Walk geht als „Gehen (Indoor)“ zu Garmin Connect – Garmins Tagesschritte ändert das nicht." : ""}
    </p>
  </Card>;
}
