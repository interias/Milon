"use client";

import { useEffect, useState } from "react";
import {
  api, type RunSummary, type VolPoint, type PacePoint, type Vo2Point, type HrPoint,
  type PaceAtHr, type EasyHr, type Trimp, type RestingHr, type FitTrend,
} from "@/lib/api";
import { Card, CardTitle, Kpi, PageTitle, Loading, ApiError } from "@/components/ui";
import { AreaTrend, Bars, MultiTrend } from "@/components/charts";
import { de, de0, pace, dm } from "@/lib/format";

// Signifikanz-Badge: nur ein statistisch belastbarer Trend (95%-CI) wird als
// besser/schlechter eingefärbt — sonst ehrlich "kein belastbarer Trend".
function TrendBadge({ t }: { t?: FitTrend }) {
  if (!t) return null;
  const good = t.verdict === "besser";
  const bad = t.verdict === "schlechter";
  const cls = good
    ? "border-good/40 bg-good/10 text-good"
    : bad
    ? "border-bad/40 bg-bad/10 text-bad"
    : "border-line bg-surface-alt text-muted";
  const txt = good ? "✓ verbessert sich" : bad ? "verschlechtert sich"
    : t.verdict === "unklar" ? "kein belastbarer Trend" : "zu wenig Daten";
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${cls}`}>
      {txt}
    </span>
  );
}

export default function Laufen() {
  const [sum, setSum] = useState<RunSummary | null>(null);
  const [vol, setVol] = useState<VolPoint[]>([]);
  const [pc, setPc] = useState<PacePoint[]>([]);
  const [vo2, setVo2] = useState<Vo2Point[]>([]);
  const [hr, setHr] = useState<HrPoint[]>([]);
  const [pah, setPah] = useState<PaceAtHr | null>(null);
  const [easy, setEasy] = useState<EasyHr | null>(null);
  const [trimp, setTrimp] = useState<Trimp | null>(null);
  const [rhr, setRhr] = useState<RestingHr | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.runSummary().then(setSum).catch((e) => setErr(String(e)));
    api.runVolume(12).then(setVol).catch(() => {});
    api.runPace(12).then(setPc).catch(() => {});
    api.runVo2(365).then(setVo2).catch(() => {});
    api.runHeartRate(26).then(setHr).catch(() => {});
    api.runPaceAtHr().then(setPah).catch(() => {});
    api.runEasyHr().then(setEasy).catch(() => {});
    api.runTrimp(26).then(setTrimp).catch(() => {});
    api.healthRestingHr(365).then(setRhr).catch(() => {});
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

      {hasHr && (
        <>
          <div className="mt-6 mb-3">
            <h2 className="font-display text-lg font-extrabold tracking-tight">Fitness-Trends</h2>
            <p className="text-xs text-muted">
              Entwicklung seit Laufbeginn — Urteil nur bei statistischer Signifikanz (95 %-CI, Lauf-Level-Regression)
            </p>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Card>
              <div className="mb-3 flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-sm font-semibold">Pace bei {de0(pah?.ref_hr)} bpm</h3>
                  <p className="text-[11px] text-muted">
                    Regression HF↔Tempo, {pah?.window_weeks ?? 8}-Wochen-Fenster — niedriger = fitter
                  </p>
                </div>
                <TrendBadge t={pah?.trend} />
              </div>
              <AreaTrend
                values={(pah?.series ?? []).map((p) => p.pace)}
                labels={(pah?.series ?? []).map((p) => dm(p.week))}
                format={pace}
                height={170}
              />
              {pah?.trend?.delta_sec_per_km != null && (
                <p className="mt-2 text-[11px] text-muted">
                  Δ {de(pah.trend.delta_sec_per_km, 1)} s/km über {pah.trend.days} Tage
                  {pah.trend.sec_per_km_per_month != null && <> ({de(pah.trend.sec_per_km_per_month, 1)} s/km pro Monat)</>}
                  {" · "}R² {de(pah.trend.r2, 2)}
                </p>
              )}
            </Card>

            <Card>
              <div className="mb-3 flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-sm font-semibold">Puls im Locker-Korridor</h3>
                  <p className="text-[11px] text-muted">
                    nur Läufe mit Pace {pace(easy?.pace_lo)}–{pace(easy?.pace_hi)} /km — niedriger = fitter
                  </p>
                </div>
                <TrendBadge t={easy?.trend} />
              </div>
              <AreaTrend
                values={(easy?.series ?? []).map((p) => p.avg_hr)}
                labels={(easy?.series ?? []).map((p) => dm(p.week))}
                format={(n) => de(n, 0)}
                unit="bpm"
                height={170}
              />
              {easy?.trend?.delta != null && easy.trend.verdict !== "wenig_daten" && (
                <p className="mt-2 text-[11px] text-muted">
                  Δ {de(easy.trend.delta, 1)} bpm über {easy.trend.days} Tage · {easy.runs} Läufe im Korridor
                </p>
              )}
            </Card>

            <Card>
              <CardTitle
                title="Trainingslast · TRIMP"
                sub="Dauer × HF-Intensität je Woche (Banister) — Belastungssteuerung, kein besser/schlechter"
              />
              <Bars
                data={(trimp?.series ?? []).slice(-12).map((p) => ({ label: dm(p.week), value: Math.round(p.trimp) }))}
                height={170}
              />
              {trimp?.avg4 != null && (
                <p className="mt-2 text-[11px] text-muted">
                  Ø letzte 4 Wochen: {de0(trimp.avg4)} · Referenzen: Ruhepuls {de0(trimp.hr_rest)}, HFmax {de0(trimp.hr_max)}
                </p>
              )}
            </Card>

            <Card>
              <div className="mb-3 flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-sm font-semibold">Ruhepuls</h3>
                  <p className="text-[11px] text-muted">niedriger = fitter · plötzlich erhöht = Ermüdung/Infekt</p>
                </div>
                <TrendBadge t={rhr?.trend} />
              </div>
              {rhr?.series?.length ? (
                <>
                  <MultiTrend
                    height={170}
                    unit="bpm"
                    format={(n) => de(n, 0)}
                    labels={rhr.series.map((p) => dm(p.date))}
                    series={[
                      { values: rhr.series.map((p) => p.bpm), label: "Tageswert", color: "var(--color-muted)" },
                      { values: rhr.series.map((p) => p.avg7), label: "7-Tage", color: "var(--color-accent)" },
                    ]}
                  />
                  <p className="mt-2 text-[11px] text-muted">
                    aktuell {de0(rhr.last)} bpm · Ø 7 Tage {de(rhr.avg7, 1)} · Trend über {rhr.trend_days} Tage
                  </p>
                </>
              ) : (
                <div style={{ height: 170 }} className="grid place-items-center text-xs text-muted">
                  keine Ruhepuls-Daten im Export — erscheint nach dem nächsten HC-Import
                </div>
              )}
            </Card>
          </div>
        </>
      )}

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
