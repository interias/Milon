"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type BodySummary, type WeightPoint, type BodyFatPoint, type Tdee, type WeeklyWeight, type Forecast, type LeanMass, type TdeePoint, type CompositionForecast } from "@/lib/api";
import { Card, CardTitle, Kpi, PageTitle, StatRow, Loading, ApiError } from "@/components/ui";
import { MultiTrend } from "@/components/charts";
import { de, de0, dm } from "@/lib/format";

const signed = (n?: number, d = 1) => (n == null ? "–" : (n > 0 ? "+" : "") + de(n, d));

// Kompakte Prognose (linear extrapoliert) statt eines eigenen Diagramms: heute / +7 T / +30 T.
function ForecastRow({ label, unit, fc }: { label: string; unit: string; fc: Forecast | null }) {
  if (!fc || fc.current == null) return null;
  const d7 = fc.current + (fc.per_week ?? 0);
  const d30 = fc.projected ?? fc.current;
  const dir = fc.per_month ?? 0;
  const cls = dir === 0 ? "text-muted" : dir < 0 ? "text-good" : "text-bad"; // runter = gut (Cut)
  return (
    <div className="rounded-card border border-line bg-surface-alt p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold">{label}</span>
        <span className={`text-xs font-bold ${cls}`}>{signed(fc.per_month)} {unit}/Monat</span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-4 gap-y-0.5 text-sm text-muted">
        <span>heute <b className="text-ink">{de(fc.current, 1)} {unit}</b></span>
        <span>+7 T <b className="text-ink">{de(d7, 1)}</b></span>
        <span>+30 T <b className="text-ink">{de(d30, 1)}</b></span>
      </div>
    </div>
  );
}

export default function Koerper() {
  const [summary, setSummary] = useState<BodySummary | null>(null);
  const [weight, setWeight] = useState<WeightPoint[]>([]);
  const [fat, setFat] = useState<BodyFatPoint[]>([]);
  const [tdee, setTdee] = useState<Tdee | null>(null);
  const [weekly, setWeekly] = useState<WeeklyWeight[]>([]);
  const [wFc, setWFc] = useState<Forecast | null>(null);
  const [cf, setCf] = useState<CompositionForecast | null>(null);
  const [lm, setLm] = useState<LeanMass | null>(null);
  const [tdeeTrend, setTdeeTrend] = useState<TdeePoint[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.bodySummary(), api.bodyWeight(180), api.bodyFat(180), api.bodyTdee(), api.bodyWeeklyWeight(12)])
      .then(([s, w, f, t, ww]) => {
        setSummary(s);
        setWeight(w);
        setFat(f);
        setTdee(t);
        setWeekly(ww);
      })
      .catch((e) => setErr(String(e)));
    api.bodyWeightForecast().then(setWFc).catch(() => {});
    api.bodyCompositionForecast().then(setCf).catch(() => {});
    api.bodyLeanMass(180).then(setLm).catch(() => {});
    api.bodyTdeeTrend(14, 180).then(setTdeeTrend).catch(() => {});
  }, []);

  if (err) return (<><PageTitle title="Körper" /><ApiError error={err} /></>);
  if (!summary || !tdee) return (<><PageTitle title="Körper" /><Loading /></>);

  const losing = (summary.weight_delta7 ?? 0) <= 0;

  return (
    <>
      <PageTitle title="Körper" sub="Gewicht, Körperfett & Energie" />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Kpi
          label="Gewicht" sub="aktuell" watermark="/img/koerper-ink-arc.png"
          value={de(summary.weight_kg, 1)} unit="kg"
          delta={`${losing ? "▼" : "▲"} ${de(Math.abs(summary.weight_delta7 ?? 0), 2)} kg / 7 T`}
          deltaKind={losing ? "good" : "bad"}
        />

        <Kpi
          label="Körperfett" sub="Anteil"
          value={de(summary.body_fat_pct, 1)} unit="%"
        />

        <Kpi
          label="TDEE" sub="Energieumsatz"
          value={de0(summary.tdee)} unit="kcal"
        />
      </div>

      {wFc?.current != null && (
        <Card className="mt-4">
          <CardTitle title="Prognose · 30 Tage" sub="am verlässlichen Gewichtstrend verankert · KFA als Spanne" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <ForecastRow label="Gewicht" unit="kg" fc={wFc} />
            {cf && cf.scenarios.length === 3 && (() => {
              const exp = cf.scenarios.find((s) => s.key === "expected");
              const lo = cf.scenarios.find((s) => s.key === "preserved");
              const hi = cf.scenarios.find((s) => s.key === "trend");
              return (
                <div className="rounded-card border border-line bg-surface-alt p-3">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-semibold">Körperfett</span>
                    <span className="text-xs font-bold text-good">
                      ~{de(exp?.bf_pct ?? null, 1)} %{" "}
                      <span className="font-normal text-muted">({de(lo?.bf_pct ?? null, 1)}–{de(hi?.bf_pct ?? null, 1)} %)</span>
                    </span>
                  </div>
                  <div className="mt-1.5 space-y-1 text-[11px]">
                    {cf.scenarios.map((s) => (
                      <div key={s.key} className={`flex items-baseline justify-between gap-2 ${s.key === "expected" ? "font-semibold text-ink" : "text-muted"}`}>
                        <span className="shrink-0">{s.label}</span>
                        <span className="text-right">{de(s.bf_pct, 1)} % · Fett {signed(s.fat_delta, 1)} · FFM {signed(s.ffm_delta, 1)} kg</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}
          </div>
          <p className="mt-3 text-[11px] text-muted">
            Gewicht ist verlässlich; der Fett-/Muskel-Anteil der Abnahme ist per Bioimpedanz-Waage nicht sicher messbar — daher eine Spanne. Bei deinem Protein (1,8 g/kg) + Training ist <b className="text-ink">Muskelerhalt</b> am wahrscheinlichsten; prüf's an{" "}
            <Link href="/kraft" className="text-accent hover:underline">Kraft/e1RM</Link> &{" "}
            <Link href="/fortschritt" className="text-accent hover:underline">Fotos</Link>.
          </p>
        </Card>
      )}

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card className="md:col-span-2">
          <CardTitle title="Gewicht · 180 Tage" sub="Rohwert + 7-Tage-Schnitt + EWMA" />
          <MultiTrend
            labels={weight.map((w) => dm(w.date))}
            unit="kg"
            height={200}
            series={[
              { values: weight.map((w) => w.weight), label: "roh", color: "var(--color-muted)" },
              { values: weight.map((w) => w.avg7), label: "7-Tage", color: "var(--color-accent-2)" },
              { values: weight.map((w) => w.ewma), label: "EWMA", color: "var(--color-accent)" },
            ]}
          />
        </Card>

        <Card>
          <CardTitle title="TDEE & Defizit" sub="Energiebilanz" />
          {tdee.tdee == null ? (
            <p className="text-sm text-muted">{tdee.reason ?? "Keine Daten verfügbar."}</p>
          ) : (
            <>
              <div className="flex items-baseline gap-1.5">
                <span className="font-display text-3xl font-extrabold tracking-tight">{de0(tdee.tdee)}</span>
                <span className="text-sm font-semibold text-muted">kcal/Tag</span>
              </div>
              <StatRow items={[
                ["Ø-Intake", `${de0(tdee.avg_intake)} kcal`],
                ["Defizit", `~${de0(tdee.deficit_per_day)} kcal/Tag`],
              ]} />
              <p className="mt-3 text-xs text-muted">
                TDEE = <b className="text-ink">14-Tage-Mittel</b> der täglichen Schätzungen (stabil) · Defizit = TDEE − Ø-Intake.
              </p>
            </>
          )}
        </Card>
      </div>

      {tdeeTrend.length > 1 && (
        <Card className="mt-4">
          <CardTitle title="TDEE-Verlauf" sub="TDEE als 14-Tage-Mittel (geglättet) · Ø-Intake vs. Umsatz (Lücke = Defizit)" />
          <MultiTrend
            labels={tdeeTrend.map((p) => dm(p.date))} unit="kcal" height={200} format={(n) => de0(n)}
            series={[
              { values: tdeeTrend.map((p) => p.intake), label: "Ø-Intake", color: "var(--color-muted)" },
              { values: tdeeTrend.map((p) => p.tdee_avg), label: "TDEE (14-T-Ø)", color: "var(--color-accent)" },
            ]}
          />
        </Card>
      )}

      {fat.length > 0 && (
        <Card className="mt-4">
          <CardTitle title="Körperfett-Trend" sub="Rohwert + 7-Tage-Schnitt" />
          <MultiTrend
            labels={fat.map((p) => dm(p.date))}
            unit="%"
            height={200}
            series={[
              { values: fat.map((p) => p.pct), label: "roh", color: "var(--color-muted)" },
              { values: fat.map((p) => p.avg7), label: "7-Tage", color: "var(--color-accent)" },
            ]}
          />
        </Card>
      )}

      {lm && lm.trend.length > 1 && (
        <Card className="mt-4">
          <CardTitle
            title="Recomp · Magermasse vs. Fettmasse"
            sub={`Gewicht × (1 − KFA %) · behalte ich im Defizit die Muskeln?`}
          />
          <MultiTrend
            labels={lm.trend.map((p) => dm(p.date))} unit="kg" height={200}
            series={[
              { values: lm.trend.map((p) => p.weight), label: "Gewicht", color: "var(--color-muted)" },
              { values: lm.trend.map((p) => p.fat), label: "Fettmasse", color: "#d9a441" },
              { values: lm.trend.map((p) => p.ffm), label: "Magermasse (FFM)", color: "var(--color-accent)" },
            ]}
          />
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-line pt-3 text-xs text-muted">
            <span>FFM aktuell <b className="text-ink">{de(lm.summary.ffm, 1)} kg</b></span>
            <span>Fettmasse <b className="text-ink">{de(lm.summary.fat, 1)} kg</b></span>
            <span className={`font-semibold ${(lm.summary.ffm_delta ?? 0) >= 0 ? "text-good" : "text-muted"}`}>FFM Δ{lm.summary.days}T {signed(lm.summary.ffm_delta ?? undefined, 2)} kg</span>
            <span className={`font-semibold ${(lm.summary.fat_delta ?? 0) <= 0 ? "text-good" : "text-bad"}`}>Fett Δ{lm.summary.days}T {signed(lm.summary.fat_delta ?? undefined, 2)} kg</span>
          </div>
        </Card>
      )}

      {weekly.length > 0 && (
        <Card className="mt-4">
          <CardTitle title="Wochenmittel · Gewicht" sub="Mittel je Woche + Veränderung zur Vorwoche" />
          <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2 lg:grid-cols-3">
            {[...weekly].reverse().map((w, i, arr) => {
              const prev = arr[i + 1]; // chronologisch ältere Woche
              const d = prev ? Math.round((w.weight - prev.weight) * 100) / 100 : null;
              return (
                <div key={w.week} className="flex items-center justify-between border-b border-line py-1.5 text-sm">
                  <span className="whitespace-nowrap text-muted">{dm(w.week)}</span>
                  <span className="whitespace-nowrap font-semibold">{de(w.weight, 1)} kg</span>
                  <span className={`w-12 text-right text-xs font-bold ${d == null ? "text-muted" : d <= 0 ? "text-good" : "text-bad"}`}>
                    {d == null ? "–" : `${d > 0 ? "+" : ""}${de(d, 2)}`}
                  </span>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </>
  );
}
