"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type TonnagePoint, type Exercise, type StrengthIndex } from "@/lib/api";
import { Card, PageTitle } from "@/components/ui";
import { RunTrendChart } from "@/components/RunTrendChart";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { StrengthDetails } from "@/components/StrengthDetails";
import { de, dm } from "@/lib/format";

const MUSCLE_ICON: Record<string, string> = {
  Beine: "beine", Brust: "brust", Rücken: "ruecken", Schultern: "schultern",
  Bizeps: "bizeps", Trizeps: "trizeps", Core: "core",
};
const PERIODS = [["1m", "1M"], ["3m", "3M"], ["6m", "6M"], ["12m", "12M"]];
const month = (date: string) => new Date(`${date.slice(0, 10)}T12:00:00`).toLocaleDateString("de-DE", { month: "short", year: "numeric" });

export default function Kraft() {
  const [exercises, setExercises] = useState<Exercise[] | null>(null);
  const [tonnage, setTonnage] = useState<TonnagePoint[] | null>(null);
  const [records, setRecords] = useState<Set<string>>(new Set());
  const [index, setIndex] = useState<StrengthIndex | null>(null);
  const [period, setPeriod] = useState("3m");
  const [indexLoading, setIndexLoading] = useState(true);
  const [errors, setErrors] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [details, setDetails] = useState(false);
  useEffect(() => {
    let active = true;
    const failed = (key: string) => { if (active) setErrors((values) => [...values, key]); };
    api.strengthExercises().then((value) => { if (active) setExercises(value); }).catch(() => failed("exercises"));
    api.strengthTonnage(12).then((value) => { if (active) setTonnage(value); }).catch(() => failed("tonnage"));
    api.strengthRecords(30, 200).then((value) => { if (active) setRecords(new Set(value.map((r) => r.exercise))); }).catch(() => {});
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    setIndexLoading(true);
    setIndex(null);
    setErrors((values) => values.filter((value) => value !== "index"));
    api.strengthIndex(period).then((value) => { if (active) setIndex(value); })
      .catch(() => { if (active) setErrors((values) => [...values, "index"]); })
      .finally(() => { if (active) setIndexLoading(false); });
    return () => { active = false; };
  }, [period]);

  const today = new Date();
  today.setHours(23, 59, 59, 999);
  const cutoff = new Date(today);
  cutoff.setDate(cutoff.getDate() - 89);
  cutoff.setHours(0, 0, 0, 0);
  const filtered = (exercises ?? []).filter((exercise) => {
    const last = new Date(`${exercise.last}T12:00:00`);
    return (showAll || (last >= cutoff && last <= today))
      && exercise.exercise.toLocaleLowerCase("de-DE").includes(query.trim().toLocaleLowerCase("de-DE"));
  });
  const groups = new Map<string, Exercise[]>();
  for (const exercise of filtered) groups.set(exercise.muscle, [...(groups.get(exercise.muscle) ?? []), exercise]);
  const latestWeek = index?.series?.at(-1)?.week;
  const chartStart = latestWeek ? new Date(`${latestWeek}T12:00:00Z`) : null;
  if (chartStart) chartStart.setUTCMonth(chartStart.getUTCMonth() - parseInt(period));
  const series = (index?.series ?? []).filter((point) => !chartStart || new Date(`${point.week}T12:00:00Z`) >= chartStart);
  const lastTonnage = tonnage?.at(-1);
  const status = (key: string, loaded: boolean) => errors.includes(key) ? "Daten konnten nicht geladen werden." : loaded ? "Noch nicht genügend Daten." : "Wird geladen …";

  return <>
    <PageTitle title="Kraft" sub="Stärkeentwicklung & Training" />
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="text-sm font-semibold">Gesamtstärke</h2>
        <div className="flex gap-1" aria-label="Zeitraum der Gesamtstärke">
          {PERIODS.map(([key, label]) => <button key={key} type="button" aria-pressed={period === key} onClick={() => setPeriod(key)} className={`rounded border px-3 py-1.5 text-xs font-semibold ${period === key ? "border-accent bg-accent text-white" : "border-line text-muted"}`}>{label}</button>)}
        </div>
      </div>
      {index?.value != null ? <>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1 tabular-nums">
          <span className="font-display text-4xl font-extrabold text-accent">{de(index.value, 0)}</span>
          <span className={`text-sm font-semibold ${index.trend === "steigt" ? "text-good" : index.trend === "faellt" ? "text-bad" : "text-muted"}`}>{index.window_delta_pct > 0 ? "+" : ""}{de(index.window_delta_pct, 1)} % · {period.toUpperCase()}</span>
        </div>
        <p className="mt-1 text-xs text-muted">Basis 100 = {month(index.base_week)}{latestWeek ? ` · zuletzt Woche ab ${dm(latestWeek)}` : ""}</p>
        <RunTrendChart label="Gesamtstärke · geglätteter Wochenverlauf" unit="Index" showPoints={false} points={series.map((point) => ({ date: point.week, value: point.smoothed }))} />
        <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
          {([["Steigende Beiträge", index.drivers_up, "text-good"], ["Fallende Beiträge", index.drivers_down, "text-bad"]] as const).map(([label, drivers, color]) => drivers?.length > 0 && <div key={label}><span className="text-muted">{label}: </span>{drivers.slice(0, 2).map((driver, i) => <span key={driver.exercise}>{i > 0 && " · "}<Link href={`/kraft/${encodeURIComponent(driver.exercise)}`} className={`${color} hover:underline`}>{driver.exercise.split(" (")[0]} {driver.pct > 0 ? "+" : ""}{de(driver.pct, 1)} %</Link></span>)}</div>)}
        </div>
      </> : <p className="mt-4 text-sm text-muted" role="status">{status("index", !indexLoading)}</p>}
      <button type="button" className="mt-4 rounded border border-line px-3 py-2 text-sm" onClick={() => setDetails(true)}>Weitere Kraftanalysen</button>
    </Card>

    <Card className="mt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div><h2 className="text-sm font-semibold">Trainingsumfang</h2><p className="mt-1 text-xs text-muted">{lastTonnage ? `Letzte erfasste Trainingswoche · ab ${dm(lastTonnage.week)}` : "Erfasste bewegte Last"}</p></div>
        <p className="text-lg font-semibold tabular-nums">{lastTonnage ? `${de(lastTonnage.tonnage_kg / 1000, 1)} t` : <span className="text-xs font-normal text-muted">{status("tonnage", tonnage != null)}</span>}</p>
      </div>
    </Card>

    <Card className="mt-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="text-sm font-semibold">Übungen</h2><p className="mt-1 text-xs text-muted">{showAll ? "Gesamte Historie" : "In den letzten 90 Tagen trainiert"} · {filtered.length} angezeigt</p></div>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} />Alle Übungen</label>
      </div>
      <input aria-label="Übung suchen" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Übung suchen …" className="my-4 w-full rounded border border-line bg-surface-alt px-3 py-2 text-base sm:text-sm" />
      {exercises == null ? <p className="text-sm text-muted" role="status">{status("exercises", false)}</p> : groups.size === 0 ? <p className="text-sm text-muted">Keine passende Übung. Über „Alle Übungen“ ist auch die ältere Historie erreichbar.</p> : <div className="space-y-4">{Array.from(groups, ([muscle, items]) => <section key={muscle}>
        <h3 className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-accent">
          {MUSCLE_ICON[muscle] && <img src={`/img/muscle/${MUSCLE_ICON[muscle]}.png`} alt="" className="h-5 w-5 object-contain" />}{muscle}
        </h3>
        {items.map((exercise) => <Link key={exercise.exercise} href={`/kraft/${encodeURIComponent(exercise.exercise)}`} className="flex items-center justify-between gap-3 border-b border-line py-2 hover:bg-surface-alt">
          <div className="min-w-0"><p className="text-sm">{records.has(exercise.exercise) && <span title="Bestleistung in den letzten 30 Tagen">🏆 </span>}{exercise.exercise}</p><p className="mt-0.5 text-xs text-muted">Zuletzt {new Date(`${exercise.last}T12:00:00`).toLocaleDateString("de-DE")}</p></div>
          <div className="shrink-0 text-right"><p className="text-sm font-semibold tabular-nums">{de(exercise.e1rm, 1)} kg</p><p className="text-[11px] text-muted">geschätztes 1RM ›</p></div>
        </Link>)}
      </section>)}</div>}
    </Card>
    {details && <RunAnalysisDialog title="Weitere Kraftanalysen" onClose={() => setDetails(false)}><StrengthDetails index={index} /></RunAnalysisDialog>}
  </>;
}
