"use client";

import { useEffect, useState } from "react";
import {
  api, type RunSummary, type VolPoint, type Vo2Point, type EfTrend, type PaceDetail,
  type EasyHr, type PaceByZone, type FitTrend, type BestEfforts, type Achievements,
} from "@/lib/api";
import { Card, CardTitle, Kpi, PageTitle, Loading, ApiError } from "@/components/ui";
import { AreaTrend, Bars, MultiTrend } from "@/components/charts";
import { AchievementsSummary, AchievementsGrid } from "@/components/Achievements";
import { de, de0, pace, dm, dur } from "@/lib/format";

// Puls-Zonen-Farben: kühl (locker Z1) → warm (hart Z4/Z5), Zuordnung folgt der ZONE-Nummer
// (Filtern/Ausblenden färbt nichts um). Als Set validiert (dataviz-Checks: CVD-ΔE ≥ 15,
// Kontrast ≥ 3:1 auf Weiß, Lightness-Band).
const ZONE_COLORS = ["#2a78d6", "#00917d", "#ab7f00", "#b53415", "#8f2e64"]; // Z1..Z5
const zoneColor = (idx: number) => ZONE_COLORS[Math.min(ZONE_COLORS.length, Math.max(1, idx)) - 1];

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
  const [pdet, setPdet] = useState<PaceDetail | null>(null);
  const [vo2, setVo2] = useState<Vo2Point[]>([]);
  const [eft, setEft] = useState<EfTrend | null>(null);
  const [easy, setEasy] = useState<EasyHr | null>(null);
  const [pbz, setPbz] = useState<PaceByZone | null>(null);
  const [best, setBest] = useState<BestEfforts | null>(null);
  const [ach, setAch] = useState<Achievements | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.runSummary().then(setSum).catch((e) => setErr(String(e)));
    api.runVolume(12).then(setVol).catch(() => {});
    api.runPaceDetail().then(setPdet).catch(() => {});
    api.runVo2(365).then(setVo2).catch(() => {});
    api.runEf().then(setEft).catch(() => {});
    api.runEasyHr().then(setEasy).catch(() => {});
    api.runPaceByZone().then(setPbz).catch(() => {});
    api.runBestEfforts().then(setBest).catch(() => {});
    api.runAchievements().then(setAch).catch(() => {});
  }, []);

  if (err) return (<><PageTitle title="Laufen" /><ApiError error={err} /></>);
  if (!sum) return (<><PageTitle title="Laufen" /><Loading /></>);

  const hasHr = (eft?.series?.length ?? 0) > 0;
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

      {ach && (
        <div className="mt-4">
          <AchievementsSummary data={ach} />
        </div>
      )}

      {best && best.distances.some((d) => d.entries.length > 0) && (
        <>
          <Card className="mt-6">
            <CardTitle title="Bestzeiten" sub="Schnellster Abschnitt innerhalb eines Laufs · je Distanz die beste Zeit" />
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-line text-xs text-muted">
                  <th scope="col" className="pb-2 text-left font-medium">Reichweite</th>
                  <th scope="col" className="pb-2 text-right font-medium">Zeit</th>
                  <th scope="col" className="pb-2 text-right font-medium">Datum</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {best.distances.filter((d) => d.entries.length > 0).map((d) => {
                  const entry = d.entries[0];
                  return (
                    <tr key={d.distance_m}>
                      <th scope="row" className="py-2 text-left font-semibold">{d.label}</th>
                      <td className="py-2 text-right font-semibold text-accent">{dur(Math.round(entry.seconds))}</td>
                      <td className="py-2 text-right text-muted">{dm(entry.date)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>

          {best.records && (
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
              {best.records.longest_run && (
                <Card>
                  <p className="text-[11px] text-muted">Längster Lauf</p>
                  <p className="font-display text-2xl font-extrabold">{de(best.records.longest_run.km, 1)} km</p>
                  <p className="text-[11px] text-muted">am {dm(best.records.longest_run.date)}</p>
                </Card>
              )}
              {best.records.biggest_week && (
                <Card>
                  <p className="text-[11px] text-muted">Größte Woche</p>
                  <p className="font-display text-2xl font-extrabold">{de(best.records.biggest_week.km, 1)} km</p>
                  <p className="text-[11px] text-muted">Wo. {dm(best.records.biggest_week.week)} · {best.records.biggest_week.runs} Läufe</p>
                </Card>
              )}
              {best.records.best_ef && (
                <Card>
                  <p className="text-[11px] text-muted">Beste aerobe Effizienz</p>
                  <p className="font-display text-2xl font-extrabold">{de(best.records.best_ef.ef, 2)}</p>
                  <p className="text-[11px] text-muted">m/Herzschlag · {dm(best.records.best_ef.date)}</p>
                </Card>
              )}
            </div>
          )}
        </>
      )}

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
                smooth
              />
              {easy?.trend?.delta != null && easy.trend.verdict !== "wenig_daten" && (
                <p className="mt-2 text-[11px] text-muted">
                  Δ {de(easy.trend.delta, 1)} bpm über {easy.trend.days} Tage · {easy.runs} Läufe im Korridor
                </p>
              )}
            </Card>

            <Card>
              <CardTitle
                title="Pace je Puls-Zone"
                sub={
                  pbz?.hr_max
                    ? `Ø-Pace je physiologischer Zone (% von HFmax ${pbz.hr_max}${pbz.hr_max_source === "einstellung" ? "" : ", aus Daten"}). Vorsicht Zonen-Wanderung: fittere Läufe rutschen in tiefere Zonen — die Linien unterschätzen den Fortschritt`
                    : "Ø-Pace je physiologischer Puls-Zone (% von HFmax)"
                }
              />
              {pbz?.zones?.length ? (
                <>
                  <MultiTrend
                    height={190}
                    format={pace}
                    labels={(pbz.weeks ?? []).map(dm)}
                    series={pbz.zones.flatMap((z) => [
                      // faint Rohwerte im Hintergrund
                      { values: z.series, color: zoneColor(z.idx), label: "", opacity: 0.28, width: 1, hideLabel: true },
                      // fette, geglättete Trendlinie (EWMA + monotone Kurve)
                      {
                        values: z.smooth ?? z.series, color: zoneColor(z.idx), smooth: true, width: 2.4,
                        label: `${z.zone} ${z.name} · ${z.hi ? `${z.lo}–${z.hi}` : `≥${z.lo}`} (${z.runs})`,
                      },
                    ])}
                  />
                  <p className="mt-2 text-[11px] text-muted">
                    Δ s/km pro Monat (Punkt-Schätzer, ohne Signifikanz):{" "}
                    {pbz.zones
                      .map((z) => `${z.zone}: ${z.sec_per_km_per_month != null ? de(z.sec_per_km_per_month, 0) : "—"}`)
                      .join(" · ")}
                  </p>
                </>
              ) : (
                <div style={{ height: 170 }} className="grid place-items-center text-xs text-muted">
                  zu wenig Läufe mit HF für Zonen-Kurven
                </div>
              )}
            </Card>
          </div>
        </>
      )}

      <div className="mt-6 mb-3">
        <h2 className="font-display text-lg font-extrabold tracking-tight">Verlauf</h2>
        <p className="text-xs text-muted">Tempo, aerobe Fitness & Volumen über die Zeit</p>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {hasHr && (
          <Card>
            <div className="mb-3 flex items-start justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold">Aerobe Effizienz</h3>
                <p className="text-[11px] text-muted">
                  Meter pro Herzschlag je Lauf + EWMA-Glättung — höher = fitter (gleiche Pace bei weniger Puls)
                </p>
              </div>
              <TrendBadge t={eft?.trend} />
            </div>
            <MultiTrend
              height={170}
              format={(n) => de(n, 2)}
              labels={(eft?.series ?? []).map((p) => dm(p.date))}
              series={[
                { values: (eft?.series ?? []).map((p) => p.ef), label: "je Lauf", color: "var(--color-accent-2)" },
                { values: (eft?.series ?? []).map((p) => p.smooth), label: "geglättet (EWMA)", color: "var(--color-accent)", smooth: true },
              ]}
            />
            {eft?.trend?.delta != null && eft.trend.verdict !== "wenig_daten" && (
              <p className="mt-2 text-[11px] text-muted">
                Δ {de(eft.trend.delta, 2)} m/Herzschlag über {eft.trend.days} Tage · {eft.runs} Läufe
              </p>
            )}
          </Card>
        )}

        <Card>
          <CardTitle title="Pace-Trend" sub="je Lauf + EWMA-Glättung · niedriger = schneller" />
          <MultiTrend
            height={170}
            format={pace}
            labels={(pdet?.series ?? []).map((p) => dm(p.date))}
            series={[
              { values: (pdet?.series ?? []).map((p) => p.pace), label: "je Lauf", color: "var(--color-accent-2)" },
              { values: (pdet?.series ?? []).map((p) => p.smooth), label: "geglättet (EWMA)", color: "var(--color-accent)", smooth: true },
            ]}
          />
          {pdet?.runs != null && (
            <p className="mt-2 text-[11px] text-muted">
              {pdet.runs} Läufe · rohe Pace mischt Intervall-/Locker-Läufe — belastbares Urteil: Karte „Puls im Locker-Korridor"
            </p>
          )}
        </Card>

        <Card className="md:col-span-2">
          <CardTitle title="Wochenvolumen · 12 Wochen" />
          <Bars data={vol.map((v) => ({ label: dm(v.week), value: Math.round(v.km) }))} unit="km" height={170} />
        </Card>

        <Card>
          <CardTitle title="VO₂max-Trend" />
          <AreaTrend values={vo2.map((p) => p.vo2)} labels={vo2.map((p) => dm(p.date))} height={170} smooth />
        </Card>
      </div>

      {ach && (
        <div className="mt-6">
          <AchievementsGrid data={ach} />
        </div>
      )}

      <div className="mt-6 flex flex-wrap gap-2">
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
