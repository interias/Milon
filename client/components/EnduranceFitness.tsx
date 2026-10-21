"use client";

import { useEffect, useState } from "react";
import { api, type EnduranceFitness } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { MultiTrend, Sparkline } from "@/components/charts";
import { de, de0, dm } from "@/lib/format";

const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${de0(Math.abs(n))}`;
const RANGES = [60, 120, 365];

function useFitness(days: number) {
  const [data, setData] = useState<EnduranceFitness | null>(null), [error, setError] = useState(false), [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setError(false);
    api.enduranceFitness(days).then((value) => { if (active) setData(value); }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [days, revision]);
  useEffect(() => {
    const refresh = () => setRevision((value) => value + 1);
    window.addEventListener("milon:data-refresh", refresh);
    return () => window.removeEventListener("milon:data-refresh", refresh);
  }, []);
  return { data, error, retry: () => setRevision((value) => value + 1) };
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return <div><p className="text-xs text-muted">{label}</p><p className="mt-1 font-display text-2xl font-extrabold tabular-nums sm:text-3xl">{value}</p>{hint && <p className="mt-1 text-xs text-muted">{hint}</p>}</div>;
}

export function EnduranceFitnessCard() {
  const [range, setRange] = useState(120);
  const { data, error, retry } = useFitness(365);
  if (!data) return <Card className="mt-4"><CardTitle title="Fitness & Frische" sub="Lauf + Rad · pulsbasierte Last" />
    <p className="text-xs text-muted" role={error ? "alert" : "status"}>{error ? "Fitness & Frische konnte nicht geladen werden. " : "wird geladen …"}{error && <button className="underline" onClick={retry}>Erneut laden</button>}</p></Card>;
  const today = data.today;
  const series = data.series.slice(-range);
  const labels = series.map((d) => dm(d.date));
  const weeks = data.weeks.slice(-8);
  const unrated = data.unrated.runs + data.unrated.rides;
  return <Card className="mt-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <CardTitle title="Fitness & Frische" sub="Lauf + Rad · pulsbasierte Last (TRIMP), Kraft zählt nicht" />
      <div className="flex gap-1" role="group" aria-label="Zeitraum">
        {RANGES.map((r) => <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}
          className={`rounded-md border px-2.5 py-1 text-xs ${range === r ? "border-accent bg-accent text-surface" : "border-line text-muted"}`}>{r === 365 ? "1 J" : `${r} T`}</button>)}
      </div>
    </div>
    {!today ? <p className="text-xs text-muted">Noch keine Einheit mit gültigem Puls. Läufe und Fahrten mit Pulsmessung erzeugen die Last.</p> : <>
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Fitness (CTL)" value={de0(today.ctl)} hint={`${data.ctl_days}-Tage-Last`} />
        <Stat label="Ermüdung (ATL)" value={de0(today.atl)} hint={`${data.atl_days}-Tage-Last`} />
        <Stat label="Form (TSB)" value={signed(today.tsb)} hint={today.form ?? undefined} />
      </div>
      <div className="mt-4">
        <MultiTrend height={170} labels={labels} format={(n) => de0(n)}
          series={[{ values: series.map((d) => d.atl), label: "Ermüdung (7 T)", color: "var(--color-warn)", opacity: 0.8, width: 1.3 },
                   { values: series.map((d) => d.ctl), label: "Fitness (42 T)", color: "var(--color-accent)", width: 2.4, smooth: true }]} />
      </div>
      <div className="mt-4 border-t border-line pt-3">
        <p className="mb-1 text-xs font-semibold">Form · Fitness minus Ermüdung vom Vorabend</p>
        <MultiTrend height={110} labels={labels} format={(n) => signed(n)} zeroLine
          series={[{ values: series.map((d) => d.tsb), label: "Form (über 0 = ausgeruht)", color: "var(--color-accent-2)", width: 2 }]} />
      </div>
      {weeks.length > 0 && <div className="mt-4 border-t border-line pt-3">
        <p className="mb-2 text-xs font-semibold">Last je Woche · Lauf und Rad</p>
        <div className="space-y-1.5">
          {(() => {
            const max = Math.max(1, ...weeks.map((w) => w.total));
            return weeks.map((w) => <div key={w.week} className="flex items-center gap-2 text-xs tabular-nums">
              <span className="w-12 shrink-0 text-muted">{dm(w.week)}</span>
              <div className="flex h-3 min-w-0 flex-1 overflow-hidden rounded bg-surface-alt" role="img"
                aria-label={`Woche ab ${dm(w.week)}: Lauf ${de0(w.run)}, Rad ${de0(w.bike)}`}>
                <div style={{ width: `${(w.run / max) * 100}%`, background: "var(--color-accent)" }} />
                <div style={{ width: `${(w.bike / max) * 100}%`, background: "var(--color-accent-2)" }} />
              </div>
              <span className="w-24 shrink-0 text-right text-muted">{w.run_share == null ? "—" : `${de0(w.run_share)} % Lauf`}</span>
            </div>);
          })()}
        </div>
        <p className="mt-2 flex gap-3 text-[10px] text-muted">
          <span className="flex items-center gap-1"><i className="inline-block h-2 w-3 rounded-sm" style={{ background: "var(--color-accent)" }} />Lauf</span>
          <span className="flex items-center gap-1"><i className="inline-block h-2 w-3 rounded-sm" style={{ background: "var(--color-accent-2)" }} />Rad</span>
        </p>
      </div>}
    </>}
    {unrated > 0 && <p className="mt-3 text-xs text-muted">{unrated} {unrated === 1 ? "Einheit" : "Einheiten"} ohne gültigen Puls ({data.unrated.runs} Lauf, {data.unrated.rides} Rad) im Zeitraum: keine Last berechnet.</p>}
    <p className="mt-2 text-[11px] text-muted">Reine Last-Kennzahlen, kein Urteil. HFmax {data.hr_max}, Ruhepuls {data.hr_rest}. Die ersten ~6 Wochen der Historie sind unterschätzt.</p>
  </Card>;
}

/** Kompakt für „Deine Woche“: Form-Zahl + Fitness-Linie. */
export function EnduranceFitnessCompact() {
  const { data } = useFitness(60);
  if (!data?.today) return null;
  const t = data.today;
  return <div className="mt-3 flex items-center gap-4 border-t border-line pt-3" aria-label="Fitness und Frische">
    <div className="shrink-0"><p className="text-xs text-muted">Form</p><p className="font-display text-2xl font-extrabold tabular-nums">{signed(t.tsb)}</p><p className="text-[11px] text-muted">{t.form}</p></div>
    <div className="min-w-0 flex-1"><Sparkline values={data.series.map((d) => d.ctl)} height={36} /><p className="mt-1 text-[11px] text-muted">Fitness {de0(t.ctl)} · Ermüdung {de0(t.atl)} · Lauf + Rad</p></div>
  </div>;
}
