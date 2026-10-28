"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Tdee } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { de0 } from "@/lib/format";

// Tagesprognose: Verbrauch heute (Grundverbrauch + Verdauung + Bewegung, mindestens typisch) vs. bisher gegessen (FDDB).
export function TodayKcal() {
  const [data, setData] = useState<Tdee | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => { api.bodyTdee().then(setData).catch(() => setError(true)); }, []);
  const forecast = data?.tdee_forecast;
  if (forecast == null) {
    return <Card className="mt-4"><CardTitle title="Kalorien heute" />
      <p className="text-xs text-muted" role="status">{error ? "Prognose konnte nicht geladen werden." : data ? data.reason ?? "Noch keine Prognose." : "Wird geladen …"}</p></Card>;
  }
  const isToday = data!.today === new Date().toLocaleDateString("sv-SE");
  const eaten = isToday ? data!.intake_today ?? 0 : 0;
  const left = forecast - eaten;
  const share = Math.min(1, eaten / forecast);
  const activeNow = isToday ? data!.active_kcal_today ?? 0 : 0;
  const activeAvg = data!.active_avg ?? 0;
  return (
    <Card className="mt-4">
      <CardTitle title="Kalorien heute" sub="Prognose aus deinem Verbrauchsmodell · gegessen laut FDDB" />
      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
        <p><span className="text-xs text-muted">Verbrauch heute ca. </span><strong className="text-2xl">{de0(Math.round(forecast / 10) * 10)}</strong> <span className="text-xs text-muted">kcal{data!.tdee_sd != null ? ` ± ${de0(data!.tdee_sd)}` : ""}</span></p>
        <p><span className="text-xs text-muted">Gegessen </span><strong className="text-2xl">{de0(eaten)}</strong> <span className="text-xs text-muted">kcal</span></p>
        <p><span className="text-xs text-muted">{left >= 0 ? "Noch übrig ca. " : "Über der Prognose "}</span><strong className={`text-2xl ${left < 0 ? "text-bad" : ""}`}>{de0(Math.abs(left))}</strong> <span className="text-xs text-muted">kcal</span></p>
      </div>
      <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-line" role="img" aria-label={`${de0(eaten)} von ${de0(forecast)} kcal gegessen`}>
        <div className={`h-full rounded-full ${left < 0 ? "bg-bad" : "bg-accent"}`} style={{ width: `${share * 100}%` }} />
      </div>
      <p className="mt-2 text-xs text-muted">
        Grundverbrauch + Verdauung {de0(data!.tdee_base)} + Bewegung {de0(Math.max(activeNow, activeAvg))}
        {activeNow >= activeAvg ? ` (bisher heute)` : ` (typisch; bisher ${de0(activeNow)})`}
        {" · "}{isToday && data!.intake_today_last ? `letzter Eintrag ${data!.intake_today_last} Uhr` : "heute noch nichts eingetragen"}
        {" · "}<Link href="/ernaehrung#energiebilanz" className="font-semibold text-accent">Energiebilanz →</Link>
      </p>
    </Card>
  );
}
