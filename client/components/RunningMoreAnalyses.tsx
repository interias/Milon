"use client";

import { useEffect, useState } from "react";
import { api, type Vo2Point, type EfTrend, type PaceDetail, type EasyHr, type PaceByZone, type FitTrend } from "@/lib/api";
import { Card, CardTitle, Loading, ApiError } from "@/components/ui";
import { AreaTrend, MultiTrend } from "@/components/charts";
import { de, pace, dm } from "@/lib/format";

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

export function RunningMoreAnalyses() {
  const [pdet, setPdet] = useState<PaceDetail | null>(null);
  const [vo2, setVo2] = useState<Vo2Point[]>([]);
  const [eft, setEft] = useState<EfTrend | null>(null);
  const [easy, setEasy] = useState<EasyHr | null>(null);
  const [pbz, setPbz] = useState<PaceByZone | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    Promise.all([api.runPaceDetail(), api.runVo2(365), api.runEf(), api.runEasyHr(), api.runPaceByZone()])
      .then(([paceData, vo2Data, efData, easyData, zoneData]) => {
        if (!active) return;
        setPdet(paceData); setVo2(vo2Data); setEft(efData); setEasy(easyData); setPbz(zoneData);
      }).catch((e) => { if (active) setError(String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  if (loading) return <Loading />;
  if (error) return <ApiError error={error} />;
  const hasHr = (eft?.series?.length ?? 0) > 0;
  return <>
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

        <Card>
          <CardTitle title="Samsung VO₂max-Trend" sub="Schätzung der Uhr · unabhängig vom eigenen VO₂-Äquivalent" />
          <AreaTrend values={vo2.map((p) => p.vo2)} labels={vo2.map((p) => dm(p.date))} height={170} smooth />
        </Card>
      </div>

    <p className="mt-4 text-xs text-muted">Höhenmeter sind in den Quelldaten nicht verfügbar.</p>
  </>;
}
