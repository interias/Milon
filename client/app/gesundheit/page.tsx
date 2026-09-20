"use client";

import { useEffect, useState } from "react";
import { api, type HealthOverview, type StepsTrendPoint } from "@/lib/api";
import { Card, PageTitle } from "@/components/ui";
import { RunTrendChart } from "@/components/RunTrendChart";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { HealthDetails } from "@/components/HealthDetails";
import { de, de0, dm } from "@/lib/format";

export default function Gesundheit() {
  const [overview, setOverview] = useState<HealthOverview | null>(null);
  const [steps, setSteps] = useState<StepsTrendPoint[] | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [raw, setRaw] = useState(false);
  const [details, setDetails] = useState(false);
  useEffect(() => {
    let active = true;
    const failed = (key: string) => { if (active) setErrors((values) => [...values, key]); };
    api.healthOverview().then((value) => { if (active) setOverview(value); }).catch(() => failed("overview"));
    api.healthSteps(30).then((value) => { if (active) setSteps(value); }).catch(() => failed("steps"));
    return () => { active = false; };
  }, []);
  const state = (key: string) => errors.includes(key) ? "Daten konnten nicht geladen werden." : "Wird geladen …";
  const summary = overview?.steps;
  const cycling = overview?.cycling;
  return <>
    <PageTitle title="Gesundheit" sub="Schritte & Alltagsbewegung" />
    <Card>
      <h2 className="text-sm font-semibold">Schritte · 7-Tage-Mittel</h2>
      {summary ? <>
        <p className="mt-3 font-display text-3xl font-extrabold">{de0(summary.avg7)} <span className="text-sm font-normal text-muted">Schritte/Tag</span></p>
        {summary.last_day ? <>
          <p className="mt-2 text-xs text-muted">{dm(summary.window_start ?? summary.last_day)}–{dm(summary.last_day)} · {summary.days7} erfasste Tage im 7-Tage-Fenster</p>
          <p className="mt-1 text-xs text-muted">Letzter erfasster Wert: {de0(summary.last)} Schritte · {new Date(`${summary.last_day}T12:00:00`).toLocaleDateString("de-DE")}</p>
        </> : <p className="mt-2 text-xs text-muted">Noch keine Schritte erfasst.</p>}
      </> : <p className="mt-3 text-xs text-muted" role="status">{state("overview")}</p>}
      {steps ? <RunTrendChart label="Schritte · 7-Tage-Mittel" unit="Schritte" showPoints={false} points={steps.map((point) => ({ date: point.date, value: point.avg7, detail: `${point.days7} erfasste Tage im 7-Tage-Fenster` }))} observations={raw ? steps.map((point) => ({ date: point.date, value: point.steps, detail: "Erfasster Tageswert" })) : []} /> : <p className="mt-4 text-xs text-muted" role="status">{state("steps")}</p>}
      <div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-muted"><span>Bis zu 30 Tage · fehlende Tage bleiben unbekannt</span><label className="flex items-center gap-2"><input type="checkbox" checked={raw} onChange={(event) => setRaw(event.target.checked)} />Tageswerte</label></div>
      {summary && <p className="mt-3 text-xs text-muted">{summary.source_label}</p>}
    </Card>
    <Card className="mt-4">
      <h2 className="text-sm font-semibold">Radfahren · letzte 30 Tage</h2>
      {cycling ? <>
        <p className="mt-3 font-display text-2xl font-extrabold">{de(cycling.km_30d, 1)} <span className="text-sm font-normal text-muted">km erfasst</span></p>
        <p className="mt-1 text-xs text-muted">{dm(cycling.window_start)}–{dm(cycling.to_date)} · getrackte Fahrten aus Health Connect</p>
        {cycling.last_ride ? <p className="mt-3 text-sm">Letzte Fahrt: {de(cycling.last_ride.km, 1)} km · {cycling.last_ride.dur_min} min · {new Date(cycling.last_ride.date).toLocaleDateString("de-DE")}</p> : <p className="mt-3 text-xs text-muted">Noch keine geeignete Fahrt erfasst.</p>}
      </> : <p className="mt-3 text-xs text-muted" role="status">{state("overview")}</p>}
    </Card>
    <button type="button" onClick={() => setDetails(true)} className="mt-4 rounded border border-line px-3 py-2 text-sm">Historie & Details</button>
    {details && <RunAnalysisDialog title="Bewegung · Historie & Details" onClose={() => setDetails(false)}><HealthDetails overview={overview} /></RunAnalysisDialog>}
  </>;
}
