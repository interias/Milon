"use client";

import { useEffect, useState } from "react";
import {
  api,
  type HealthOverview, type StepsTrendPoint, type StepsWeek,
  type CyclingWeek, type CyclingRide,
} from "@/lib/api";
import { Card, CardTitle, Kpi, PageTitle, StatRow, Loading, ApiError } from "@/components/ui";
import { Bars, MultiTrend } from "@/components/charts";
import { de, de0, dm, isToday } from "@/lib/format";

const ACCENT = "var(--color-accent)";
const RAW = "#b9c6c3";

export default function Gesundheit() {
  const [ov, setOv] = useState<HealthOverview | null>(null);
  const [steps, setSteps] = useState<StepsTrendPoint[]>([]);
  const [stepsW, setStepsW] = useState<StepsWeek[]>([]);
  const [cyc, setCyc] = useState<CyclingWeek[]>([]);
  const [rides, setRides] = useState<CyclingRide[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.healthOverview().then(setOv).catch((e) => setErr(String(e)));
    api.healthSteps(30).then(setSteps).catch(() => {});
    api.healthStepsWeekly(12).then(setStepsW).catch(() => {});
    api.healthCycling(12).then(setCyc).catch(() => {});
    api.healthCyclingRecent(8).then(setRides).catch(() => {});
  }, []);

  if (err) return (<><PageTitle title="Gesundheit" /><ApiError error={err} /></>);
  if (!ov) return (<><PageTitle title="Gesundheit" /><Loading /></>);

  const s = ov.steps;
  const c = ov.cycling;

  return (
    <>
      <PageTitle title="Gesundheit" sub="Schritte & Radfahren · allgemeine Gesundheitswerte aus Health Connect" />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Kpi
          label={isToday(s.last_day) ? "Schritte heute" : "Schritte zuletzt"}
          sub={s.last_day ? `Stand ${dm(s.last_day)}` : "Health Connect"}
          watermark="/img/koerper-ink-arc.png"
          value={de0(s.last)}
        >
          <StatRow items={[["Ø 7 Tage", de0(s.avg7)], ["Ø 30 Tage", de0(s.avg30)]]} />
        </Kpi>

        <Kpi
          label="Bestwert" sub={`${s.total_days} Tage erfasst`}
          value={de0(s.best)} unit="Schritte"
        />

        <Kpi
          label="Radfahren" sub={`${c.rides} Fahrten${c.last_day ? ` · zuletzt ${dm(c.last_day)}` : ""}`}
          value={de(c.total_km, 0)} unit="km gesamt"
        >
          <StatRow items={[["letzte 30 T", `${de(c.km_30d, 0)} km`], ["Ø Tempo", `${de(c.avg_speed, 1)} km/h`]]} />
        </Kpi>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card className="md:col-span-2">
          <CardTitle title="Schritte · 30 Tage" sub="Tageswert + 7-Tage-Schnitt" />
          <MultiTrend
            labels={steps.map((p) => dm(p.date))}
            series={[
              { label: "Tag", color: RAW, values: steps.map((p) => p.steps) },
              { label: "Ø 7 Tage", color: ACCENT, values: steps.map((p) => p.avg7) },
            ]}
            format={(n) => de0(n)}
            height={180}
          />
        </Card>

        <Card>
          <CardTitle title="Wochenschritte · 12 Wochen" sub="Summe je Woche (in Tausend)" />
          <Bars
            data={stepsW.map((w) => ({ label: dm(w.week), value: Math.round(w.steps / 1000) }))}
            unit="k" height={170}
          />
        </Card>

        <Card>
          <CardTitle title="Rad · Wochenvolumen" sub="12 Wochen" />
          <Bars
            data={cyc.map((w) => ({ label: dm(w.week), value: Math.round(w.km) }))}
            unit="km" height={170}
          />
        </Card>

        <Card className="md:col-span-2">
          <CardTitle title="Letzte Fahrten" />
          {rides.length === 0 ? (
            <p className="text-sm text-muted">Keine Fahrten erfasst.</p>
          ) : (
            <ul className="divide-y divide-line">
              {rides.map((r, i) => (
                <li key={i} className="flex items-center gap-2.5 py-2">
                  <span className="text-base">🚴</span>
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold">{de(r.km, 1)} km</span>
                  <span className="shrink-0 text-xs text-muted">{r.dur_min} min · {de(r.speed, 1)} km/h</span>
                  <span className="w-12 shrink-0 text-right text-[11px] text-muted">{dm(r.date)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <p className="mt-4 text-[11px] text-muted">
        Quelle: Health Connect · Radfahren = getrackte Rad-Sessions (Samsung Health). Schritte je Tag
        aus der vollständigsten App (keine Doppelzählung Watch + Handy).
      </p>
    </>
  );
}
