"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type StrengthSummary, type TonnagePoint, type RpePoint, type Exercise, type StrengthIndex, type StrengthEnergy } from "@/lib/api";
import { Card, CardTitle, Kpi, PageTitle, Loading, ApiError } from "@/components/ui";
import { AreaTrend, Bars, MultiTrend, DualAxisTrend } from "@/components/charts";
import { de, de0, dm } from "@/lib/format";

const COMPOUND = /squat|kniebeuge|bench|bankdr|deadlift|kreuzheb/i;
const MUSCLE_ICON: Record<string, string> = {
  Beine: "beine", Brust: "brust", "Rücken": "ruecken", Schultern: "schultern",
  Bizeps: "bizeps", Trizeps: "trizeps", Core: "core",
};

const IDX_PERIODS: [string, string][] = [["1m", "1M"], ["3m", "3M"], ["6m", "6M"], ["12m", "12M"]];
// Anzahl angezeigter Wochenpunkte je Fenster (wöchentliche Auflösung)
const IDX_SLICE: Record<string, number> = { "1m": 6, "3m": 13, "6m": 26, "12m": 52 };
const TREND: Record<string, { cls: string; icon: string }> = {
  steigt: { cls: "text-good", icon: "▲" }, stagniert: { cls: "text-muted", icon: "→" }, faellt: { cls: "text-bad", icon: "▼" },
};
const PHASE: Record<string, { cls: string; icon: string }> = {
  cut: { cls: "text-bad", icon: "▼" }, recomp: { cls: "text-good", icon: "▲" },
  aufbau: { cls: "text-good", icon: "▲" }, stabil: { cls: "text-muted", icon: "→" },
};
const MON = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
const fmtMonth = (m: string) => { const [y, mo] = m.split("-"); return `${MON[+mo - 1]} ${y.slice(2)}`; };
const fmtWeek = (w: string) => { const [, mo, d] = w.split("-"); return `${d}.${mo}.`; };
const exShort = (e: string) => e.split(" (")[0];

export default function Kraft() {
  const [summary, setSummary] = useState<StrengthSummary | null>(null);
  const [tonnage, setTonnage] = useState<TonnagePoint[]>([]);
  const [rpe, setRpe] = useState<RpePoint[]>([]);
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [prSet, setPrSet] = useState<Set<string>>(new Set());
  const [idx, setIdx] = useState<StrengthIndex | null>(null);
  const [idxPeriod, setIdxPeriod] = useState("3m");
  const [energy, setEnergy] = useState<StrengthEnergy | null>(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.strengthSummary(), api.strengthTonnage(12), api.strengthRpe(12), api.strengthExercises()])
      .then(([s, t, r, ex]) => {
        setSummary(s);
        setTonnage(t);
        setRpe(r);
        setExercises(ex);
      })
      .catch((e) => setErr(String(e)));
    // Übungen mit Bestleistung in den letzten 30 Tagen → 🏆 in der Liste
    api.strengthRecords(30, 200).then((rs) => setPrSet(new Set(rs.map((r) => r.exercise)))).catch(() => {});
  }, []);

  useEffect(() => {
    api.strengthIndex(idxPeriod).then(setIdx).catch(() => {});
  }, [idxPeriod]);

  useEffect(() => {
    api.strengthEnergy().then(setEnergy).catch(() => {});
  }, []);

  if (err) return (<><PageTitle title="Kraft" sub="e1RM, Tonnage & RPE" /><ApiError error={err} /></>);
  if (!summary) return (<><PageTitle title="Kraft" sub="e1RM, Tonnage & RPE" /><Loading /></>);

  const lifts = summary.main_lifts ?? [];
  const compounds = lifts.filter((l) => COMPOUND.test(l.exercise));
  const feat = compounds.length
    ? compounds.reduce((a, c) => (c.e1rm > a.e1rm ? c : a))
    : lifts[0] ?? null;

  const filtered = exercises.filter((e) => e.exercise.toLowerCase().includes(q.toLowerCase()));
  const byMuscle = new Map<string, Exercise[]>();
  for (const e of filtered) {
    const arr = byMuscle.get(e.muscle) ?? [];
    arr.push(e);
    byMuscle.set(e.muscle, arr);
  }
  const groups = Array.from(byMuscle.entries());

  return (
    <>
      <PageTitle title="Kraft" sub="e1RM, Tonnage & RPE" />

      {idx && idx.series && idx.series.length >= 2 && (() => {
        const t = TREND[idx.trend] ?? TREND.stagniert;
        const sliced = idx.series.slice(-(IDX_SLICE[idx.period] ?? 4));
        const trendLabel = idx.trend === "faellt" ? "fällt" : idx.trend;
        return (
          <Card className="mb-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle title="Gesamtstärke" sub={`Index aller aktiven Übungen · Basis 100 = Start ${fmtMonth(idx.base_week)}`} />
                <div className="flex items-baseline gap-2">
                  <span className="font-display text-4xl font-extrabold tracking-tight text-accent">{idx.value}</span>
                  <span className={`text-sm font-bold ${t.cls}`}>{t.icon} {de(Math.abs(idx.window_delta_pct), 1)}%</span>
                  <span className="text-xs text-muted">{idxPeriod.toUpperCase()} · {trendLabel}</span>
                </div>
              </div>
              <div className="inline-flex flex-wrap gap-1 rounded-lg border border-line bg-surface p-1">
                {IDX_PERIODS.map(([k, l]) => (
                  <button
                    key={k} type="button" onClick={() => setIdxPeriod(k)}
                    className={"rounded-md px-3 py-1.5 text-xs font-semibold transition-colors " + (idxPeriod === k ? "bg-accent text-white" : "text-muted hover:text-ink")}
                  >
                    {l}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-3">
              <MultiTrend
                labels={sliced.map((p) => (idx.period === "1m" || idx.period === "3m") ? fmtWeek(p.week) : fmtMonth(p.week))}
                height={170} format={(n) => de0(n)}
                series={[
                  { values: sliced.map((p) => p.raw), label: "Woche (roh)", color: "var(--color-muted)" },
                  { values: sliced.map((p) => p.anchor), label: "Monats-Anker", color: "#d9a441" },
                  { values: sliced.map((p) => p.smoothed), label: "Index", color: "var(--color-accent)" },
                ]}
              />
            </div>
            {(idx.drivers_up.length > 0 || idx.drivers_down.length > 0) && (
              <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs">
                {idx.drivers_up.length > 0 && (
                  <span className="text-muted">
                    Treiber:{" "}
                    {idx.drivers_up.map((d, i) => (
                      <span key={d.exercise}>
                        <Link href={`/kraft/${encodeURIComponent(d.exercise)}`} className="font-medium text-good hover:underline">{exShort(d.exercise)} +{de(d.pct, 1)}%</Link>
                        {i < idx.drivers_up.length - 1 ? " · " : ""}
                      </span>
                    ))}
                  </span>
                )}
                {idx.drivers_down.length > 0 && (
                  <span className="text-muted">
                    Bremse:{" "}
                    {idx.drivers_down.map((d, i) => (
                      <span key={d.exercise}>
                        <Link href={`/kraft/${encodeURIComponent(d.exercise)}`} className="font-medium text-bad hover:underline">{exShort(d.exercise)} −{de(Math.abs(d.pct), 1)}%</Link>
                        {i < idx.drivers_down.length - 1 ? " · " : ""}
                      </span>
                    ))}
                  </span>
                )}
              </div>
            )}
            <p className="mt-2 text-[11px] text-muted">
              {idx.cohort_size} aktive Übungen · {idx.groups} Muskelgruppen gewichtet · wöchentlich, driftfrei am Monats-Anker verankert (robust gegen Übungswechsel). Maschinen-e1RM ist eine Näherung, kein 1RM-Test — mehr Volumen erhöht den Index nicht, nur höhere Last.
            </p>
          </Card>
        );
      })()}

      {energy && energy.series && energy.series.length >= 4 && (() => {
        const p = PHASE[energy.phase] ?? PHASE.stabil;
        const ser = energy.series;
        const fmtDef = (n: number) => (n > 0 ? "+" : "") + de0(n);
        const phaseRead =
          energy.phase === "cut" ? "kostet der Cut aktuell etwas Kraft"
          : energy.phase === "recomp" ? "hält die Kraft trotz Defizit (Recomp)"
          : energy.phase === "aufbau" ? "baut der Überschuss Kraft auf"
          : "ist die Lage stabil";
        return (
          <Card className="mb-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <CardTitle title="Stärke vs. Energiebilanz" sub="Wird mein Defizit zur Stärkebremse?" />
              <span className={`shrink-0 rounded-full border border-line px-2.5 py-1 text-xs font-semibold ${p.cls}`}>{p.icon} {energy.phase_label}</span>
            </div>
            <p className="mt-1 text-sm text-muted">
              Letzte {energy.recent_weeks} Wochen: Index{" "}
              <span className={`font-semibold ${energy.recent_index_delta < 0 ? "text-bad" : "text-good"}`}>
                {energy.recent_index_delta > 0 ? "+" : ""}{de(energy.recent_index_delta, 1)}
              </span>{" "}
              bei Ø {fmtDef(energy.recent_deficit_avg)} kcal/Tag {energy.recent_deficit_avg >= 0 ? "Defizit" : "Überschuss"}.
            </p>
            <div className="mt-3">
              <DualAxisTrend
                labels={ser.map((s) => fmtMonth(s.week))}
                height={200}
                left={{ values: ser.map((s) => s.index), label: "Index", color: "var(--color-accent)" }}
                right={{ values: ser.map((s) => s.deficit), label: "Defizit (kcal/Tag)", color: "#bd7b1a", format: fmtDef }}
              />
            </div>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
              <span>Woche-zu-Woche: <b className="text-ink">r ≈ {de(energy.corr_change_deficit ?? 0, 2)}</b> (belastbar → kein Dauergesetz)</span>
              <span>Niveau: r = {de(energy.corr_index_deficit ?? 0, 2)} (trendgetrieben, scheinbar)</span>
            </div>
            <p className="mt-2 text-[11px] text-muted">
              {energy.n_weeks} Wochen · TDEE Ø {de0(energy.tdee_avg)} kcal. Index und Defizit laufen über die Zeit beide als Trend → die Niveau-Korrelation überzeichnet; entkoppelt ist der Zusammenhang ~0. Belastbar ist der Phasen-Read: {phaseRead}.
            </p>
          </Card>
        );
      })()}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Kpi
          label="Top-Lift" sub={feat ? feat.exercise : "Kraftaufbau"} watermark="/img/kraft-ink-slash.png"
          value={de0(feat?.e1rm)} unit="kg e1RM"
        />

        <Kpi
          label="Wochen-Tonnage" sub="bewegte Last"
          value={de((summary.week_tonnage_kg ?? 0) / 1000, 1)} unit="t"
        />

        <Kpi
          label="RPE Ø" sub="Anstrengung"
          value={de(summary.rpe, 1)}
        />
      </div>

      <Card className="mt-4">
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle title="Übungen" sub={`${exercises.length} gesamt · nach Muskelgruppe`} />
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Übung suchen …"
            className="rounded-lg border border-line bg-surface-alt px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-accent focus:outline-none sm:w-56"
          />
        </div>
        {groups.length === 0 ? (
          <p className="text-sm text-muted">Keine Übung gefunden.</p>
        ) : (
          <div className="flex flex-col gap-4">
            {groups.map(([muscle, items]) => (
              <div key={muscle}>
                <div className="mb-1 flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    {MUSCLE_ICON[muscle] && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={`/img/muscle/${MUSCLE_ICON[muscle]}.png`} alt="" className="h-5 w-5 object-contain" />
                    )}
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-accent">{muscle}</h4>
                  </div>
                  <span className="text-[11px] text-muted">{items.length}</span>
                </div>
                {items.map((l, i) => (
                  <Link
                    key={l.exercise}
                    href={`/kraft/${encodeURIComponent(l.exercise)}`}
                    className={`-mx-2 flex items-center justify-between gap-3 rounded-lg px-2 py-2 hover:bg-surface-alt ${i ? "border-t border-line" : ""}`}
                  >
                    <span className="flex min-w-0 flex-1 items-center gap-1.5 text-sm">
                      {prSet.has(l.exercise) && <span title="Bestleistung in den letzten 30 Tagen">🏆</span>}
                      <span className="truncate">{l.exercise}</span>
                    </span>
                    <div className="flex shrink-0 items-center gap-2 text-right">
                      <div>
                        <div className="text-sm font-bold">{de0(l.e1rm)} kg</div>
                        <div className="text-[11px] text-muted">Peak {de0(l.peak)} · {de0(l.sets)} Sätze</div>
                      </div>
                      <span className="text-muted">›</span>
                    </div>
                  </Link>
                ))}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="mt-4">
        <CardTitle title="Wochen-Tonnage (12 Wochen)" />
        <Bars
          data={tonnage.map((t) => ({ label: dm(t.week), value: Math.round(t.tonnage_kg / 1000) }))}
          unit="t"
          height={170}
        />
      </Card>

      <Card className="mt-4">
        <CardTitle title="RPE-Trend" sub="Ermüdungssignal" />
        <AreaTrend values={rpe.map((r) => r.rpe)} labels={rpe.map((r) => dm(r.week))} height={170} />
      </Card>
    </>
  );
}
