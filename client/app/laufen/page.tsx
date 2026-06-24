"use client";

import { useEffect, useState } from "react";
import { api, type RunSummary, type VolPoint, type PacePoint, type Vo2Point } from "@/lib/api";
import { Card, CardTitle, Kpi, PageTitle, StatRow, Loading, ApiError } from "@/components/ui";
import { AreaTrend, Bars } from "@/components/charts";
import { de, de0, pace, dm } from "@/lib/format";

export default function Laufen() {
  const [sum, setSum] = useState<RunSummary | null>(null);
  const [vol, setVol] = useState<VolPoint[]>([]);
  const [pc, setPc] = useState<PacePoint[]>([]);
  const [vo2, setVo2] = useState<Vo2Point[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.runSummary().then(setSum).catch((e) => setErr(String(e)));
    api.runVolume(12).then(setVol).catch(() => {});
    api.runPace(12).then(setPc).catch(() => {});
    api.runVo2(365).then(setVo2).catch(() => {});
  }, []);

  if (err) return (<><PageTitle title="Laufen" /><ApiError error={err} /></>);
  if (!sum) return (<><PageTitle title="Laufen" /><Loading /></>);

  return (
    <>
      <PageTitle title="Laufen" sub="Volumen, Tempo & VO₂max" />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
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
      </div>

      <div className="mt-4">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-alt px-2.5 py-1 text-[11px] text-muted">
          ⛰ Höhenmeter: nicht verfügbar
        </span>
      </div>
    </>
  );
}