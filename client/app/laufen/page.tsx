"use client";

import { useEffect, useState } from "react";
import { api, type RunSummary, type VolPoint, type PacePoint, type Vo2Point, type HrPoint } from "@/lib/api";
import { Card, CardTitle, Kpi, PageTitle, Loading, ApiError } from "@/components/ui";
import { AreaTrend, Bars, MultiTrend } from "@/components/charts";
import { de, de0, pace, dm } from "@/lib/format";

export default function Laufen() {
  const [sum, setSum] = useState<RunSummary | null>(null);
  const [vol, setVol] = useState<VolPoint[]>([]);
  const [pc, setPc] = useState<PacePoint[]>([]);
  const [vo2, setVo2] = useState<Vo2Point[]>([]);
  const [hr, setHr] = useState<HrPoint[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.runSummary().then(setSum).catch((e) => setErr(String(e)));
    api.runVolume(12).then(setVol).catch(() => {});
    api.runPace(12).then(setPc).catch(() => {});
    api.runVo2(365).then(setVo2).catch(() => {});
    api.runHeartRate(26).then(setHr).catch(() => {});
  }, []);

  if (err) return (<><PageTitle title="Laufen" /><ApiError error={err} /></>);
  if (!sum) return (<><PageTitle title="Laufen" /><Loading /></>);

  const hasHr = hr.length > 0;
  // HF-Werte stammen aus der letzten Woche MIT HF-Läufen — ist die älter als die
  // letzte Lauf-Woche (Watch nicht getragen), die Woche im KPI ausweisen.
  const lastVolWeek = vol.length > 0 ? vol[vol.length - 1].week : null;
  const hrStale = !!(sum.hr_week && lastVolWeek && sum.hr_week !== lastVolWeek);

  return (
    <>
      <PageTitle title="Laufen" sub="Volumen, Tempo, VO₂max & Herzfrequenz" />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          label="Wochenvolumen" sub={`${de0(sum.week_runs)} Läufe`} watermark="/img/run-teal-solid.png"
          value={de(sum.week_km, 1)} unit="km/Wo"
        />
        <Kpi
          label="Pace" sub="pro Kilometer"
          value={pace(sum.pace)} unit="/km"
        />
        <Kpi
          label="VO₂max" sub="aerobe Fitness"
          value={de0(sum.vo2max)}
        />
        <Kpi
          label="Ø-Puls"
          sub={
            sum.avg_hr == null ? "noch keine HF-Daten"
            : hrStale ? `max ${de0(sum.max_hr)} · Wo. ${dm(sum.hr_week!)}`
            : `max ${de0(sum.max_hr)} bpm`
          }
          value={de0(sum.avg_hr)} unit={sum.avg_hr != null ? "bpm" : undefined}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card className="md:col-span-2">
          <CardTitle title="Wochenvolumen · 12 Wochen" />
          <Bars data={vol.map((v) => ({ label: dm(v.week), value: Math.round(v.km) }))} unit="km" height={170} />
        </Card>

        <Card>
          <CardTitle title="Pace-Trend" sub="niedriger = schneller" />
          <AreaTrend values={pc.map((p) => p.pace)} labels={pc.map((p) => dm(p.week))} format={pace} height={170} />
        </Card>

        <Card>
          <CardTitle title="VO₂max-Trend" />
          <AreaTrend values={vo2.map((p) => p.vo2)} labels={vo2.map((p) => dm(p.date))} height={170} />
        </Card>

        {hasHr && (
          <>
            <Card>
              <CardTitle title="Herzfrequenz · Wochen" sub="Ø und Max über alle Läufe mit HF" />
              <MultiTrend
                height={170}
                unit="bpm"
                format={(n) => de(n, 0)}
                labels={hr.map((p) => dm(p.week))}
                series={[
                  { values: hr.map((p) => p.max_hr), label: "Max-HF", color: "var(--color-muted)" },
                  { values: hr.map((p) => p.avg_hr), label: "Ø-HF", color: "var(--color-accent)" },
                ]}
              />
            </Card>

            <Card>
              <CardTitle title="Aerobe Effizienz" sub="Meter pro Herzschlag — höher = fitter (gleiche Pace bei weniger Puls)" />
              <AreaTrend
                values={hr.map((p) => p.ef)}
                labels={hr.map((p) => dm(p.week))}
                format={(n) => de(n, 2)}
                height={170}
              />
            </Card>

            <Card>
              <CardTitle title="HF-Drift" sub="Ø-HF 2. vs. 1. Hälfte je Lauf — niedriger = stabilere Ausdauer" />
              <AreaTrend
                values={hr.map((p) => p.drift)}
                labels={hr.map((p) => dm(p.week))}
                format={(n) => de(n, 1)}
                unit="%"
                height={170}
                className="text-accent-2"
              />
            </Card>
          </>
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-alt px-2.5 py-1 text-[11px] text-muted">
          ⛰ Höhenmeter: nicht verfügbar
        </span>
        {!hasHr && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-alt px-2.5 py-1 text-[11px] text-muted">
            ♥ Herzfrequenz: erscheint nach dem nächsten Health-Connect-Import
          </span>
        )}
      </div>
    </>
  );
}
