"use client";

import { useEffect, useState } from "react";
import { api, type HealthOverview, type StepsWeek, type CyclingWeek, type CyclingRide } from "@/lib/api";
import { RunTrendChart } from "@/components/RunTrendChart";
import { Bars } from "@/components/charts";
import { de, de0, dm } from "@/lib/format";

export function HealthDetails({ overview }: { overview: HealthOverview | null }) {
  const [weeks, setWeeks] = useState<StepsWeek[] | null>(null);
  const [cycling, setCycling] = useState<CyclingWeek[] | null>(null);
  const [rides, setRides] = useState<CyclingRide[] | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  useEffect(() => {
    let active = true;
    const failed = (key: string) => { if (active) setErrors((values) => [...values, key]); };
    api.healthStepsWeekly(12).then((value) => { if (active) setWeeks(value); }).catch(() => failed("steps"));
    api.healthCycling(12).then((value) => { if (active) setCycling(value); }).catch(() => failed("cycling"));
    api.healthCyclingRecent(0).then((value) => { if (active) setRides(value); }).catch(() => failed("rides"));
    return () => { active = false; };
  }, []);
  const state = (key: string, loaded: boolean) => errors.includes(key) ? "Daten konnten nicht geladen werden." : loaded ? "Noch keine Daten erfasst." : "Wird geladen …";
  return <div className="space-y-6 text-sm">
    <section>
      <h3 className="font-semibold">Schritte · ergänzende Werte</h3>
      {overview ? <>
        <p className="mt-2">Bestwert {de0(overview.steps.best)} Schritte · {overview.steps.total_days} Tage insgesamt erfasst.</p>
        <p className="mt-1 text-xs text-muted">Ø {de0(overview.steps.avg30)} Schritte/Tag · {overview.steps.days30} erfasste Tage im 30-Tage-Fenster{overview.steps.last_day ? ` bis ${dm(overview.steps.last_day)}` : ""}.</p>
      </> : <p className="mt-2 text-xs text-muted">Zusammenfassung nicht verfügbar.</p>}
      <h3 className="mt-4 font-semibold">Wochensummen · letzte zwölf Kalenderwochen im Datenverlauf</h3>
      {weeks?.length ? <RunTrendChart label="Erfasste Wochenschritte" unit="Schritte" points={weeks.map((point) => ({ date: point.week, value: point.steps, detail: `Woche bis ${dm(point.week)} · ${point.days}/7 Tage erfasst` }))} /> : <p className="mt-2 text-xs text-muted">{state("steps", weeks != null)}</p>}
      <p className="mt-2 text-xs text-muted">Unvollständige Wochen sind nicht direkt mit vollständig erfassten Wochen vergleichbar. Ein erfasster Tag belegt keine ganztägige Aufzeichnung.</p>
    </section>
    <section className="border-t border-line pt-4">
      <h3 className="font-semibold">Radfahren · Historie</h3>
      {overview && <p className="mt-2">{de(overview.cycling.total_km, 1)} km · {overview.cycling.rides} Fahrten insgesamt · Ø {de(overview.cycling.avg_speed, 1)} km/h</p>}
      {cycling?.length ? <div className="mt-3"><Bars data={cycling.map((point) => ({ label: dm(point.week), value: point.km }))} unit="km" height={220} /></div> : <p className="mt-2 text-xs text-muted">{state("cycling", cycling != null)}</p>}
      <p className="mt-2 text-xs text-muted">Letzte zwölf Wochen mit erfassten Fahrten · Wochenbeginn Montag. Nicht aufgezeichnete Fahrten bleiben unbekannt.</p>
      <h3 className="mt-4 font-semibold">Alle erfassten Fahrten</h3>
      {rides?.length ? <ul className="mt-2 divide-y divide-line">{rides.map((ride, index) => <li key={`${ride.date}-${index}`} className="flex flex-wrap justify-between gap-x-4 gap-y-1 py-2"><span>{new Date(ride.date).toLocaleDateString("de-DE")}</span><span className="tabular-nums">{de(ride.km, 1)} km · {ride.dur_min} min · {de(ride.speed, 1)} km/h</span></li>)}</ul> : <p className="mt-2 text-xs text-muted">{state("rides", rides != null)}</p>}
    </section>
  </div>;
}
