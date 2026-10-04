"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type WeeklyReview as Review } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { de, de0, dm } from "@/lib/format";

const change = (value: number | null, unit: string, digits = 1) => value == null ? "Vergleich noch nicht verfügbar" : `${value > 0 ? "+" : ""}${de(value, digits)} ${unit} gegenüber davor`;

export function WeeklyReview() {
  const [data, setData] = useState<Review | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    api.weeklyReview().then((value) => { if (active) setData(value); }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, []);
  const a = data?.activity;
  const stepsComparable = a?.steps.current_days === 7 && a.steps.previous_days === 7;
  return <Card className="mt-4">
    <CardTitle title="Deine Wochenbilanz" sub={a ? `${dm(a.from_date)}–${dm(a.to_date)} · sieben abgeschlossene Kalendertage` : "Training, Körper und Erholung zusammen"} />
    {data && a ? <>
      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
        <div><p className="text-xs text-muted">Laufen</p><p className="mt-1 font-display text-2xl font-bold">{de(a.running.current_km, 1)} <span className="text-xs font-normal">km</span></p><p className="mt-2 text-xs text-muted">{change(a.running.current_km - a.running.previous_km, "km")}</p></div>
        <div><p className="text-xs text-muted">Krafttraining</p><p className="mt-1 font-display text-2xl font-bold">{de0(a.strength.current_sessions)} <span className="text-xs font-normal">{a.strength.current_sessions === 1 ? "Einheit" : "Einheiten"}</span></p><p className="mt-2 text-xs text-muted">{change(a.strength.current_sessions - a.strength.previous_sessions, Math.abs(a.strength.current_sessions - a.strength.previous_sessions) === 1 ? "Einheit" : "Einheiten", 0)}</p></div>
        <div><p className="text-xs text-muted">Gewichtsverlauf</p><p className="mt-1 font-display text-2xl font-bold">{data.weight.delta_kg == null ? "—" : `${data.weight.delta_kg > 0 ? "+" : ""}${de(data.weight.delta_kg, 2)}`} <span className="text-xs font-normal">kg</span></p><p className="mt-2 text-xs text-muted">Wochenmittel · {data.weight.current_days}/7 Messtage, davor {data.weight.previous_days}/7</p></div>
        <div><p className="text-xs text-muted">Schlaf</p><p className="mt-1 font-display text-2xl font-bold">{de(data.sleep.avg_hours, 1)} <span className="text-xs font-normal">h / Nacht</span></p><p className="mt-2 text-xs text-muted">{data.sleep.measured_nights}/7 Nächte mit bekannter Schlafzeit</p></div>
      </div>
      <p className="mt-5 border-t border-line pt-3 text-xs text-muted">Alltagsbewegung: {de0(a.steps.current_avg)} Schritte je erfasstem Tag · {a.steps.current_days}/7 Tage{stepsComparable && a.steps.current_avg != null && a.steps.previous_avg != null ? ` · ${change(a.steps.current_avg - a.steps.previous_avg, "Schritte", 0)}` : " · kein vollständiger Vergleich"}</p>
      <p className="mt-2 text-xs text-muted">{data.note}</p>
      {data.checkins.count > 0 && <p className="mt-2 text-xs text-muted">Freiwillige Check-ins: {data.checkins.count}/7 Tage · Energie {de(data.checkins.energy_avg, 1)}/5 aus {data.checkins.energy_days} Angaben</p>}
      <Link href="/coach" className="mt-3 inline-block py-1 text-xs font-semibold text-accent">Mit dem Coach einordnen →</Link>
    </> : <p role="status" className="text-sm text-muted">{error ? "Wochenbilanz konnte nicht geladen werden." : "Wird geladen …"}</p>}
  </Card>;
}
