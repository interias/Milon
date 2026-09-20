"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, type ExerciseDetail } from "@/lib/api";
import { Card } from "@/components/ui";
import { RunTrendChart } from "@/components/RunTrendChart";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { de, dm } from "@/lib/format";

const PERIODS = [["1m", "1 Monat"], ["3m", "3 Monate"], ["12m", "12 Monate"], ["all", "Gesamt"]];
const METRICS = {
  e1rm: { label: "Geschätzte Maximalkraft", unit: "kg", note: "e1RM nach Epley aus dem besten Arbeitssatz je Trainingstag; kein gemessener Maximalkrafttest." },
  top_weight: { label: "Trainingsgewicht", unit: "kg", note: "Schwerster erfasster Arbeitssatz je Trainingstag." },
  tonnage: { label: "Bewegte Last", unit: "kg", note: "Gewicht × Wiederholungen, summiert je Trainingstag. Mehr Last bedeutet nicht automatisch mehr Kraft." },
  rpe: { label: "Anstrengung (RPE)", unit: "RPE", note: "Mittlere erfasste Satzbewertung je Trainingstag. Höher bedeutet mehr subjektive Anstrengung; fehlende Angaben bleiben leer." },
};
type Metric = keyof typeof METRICS;

export default function ExerciseDetailPage() {
  const params = useParams();
  const raw = Array.isArray(params.exercise) ? params.exercise[0] : (params.exercise ?? "");
  let name = raw;
  try { name = decodeURIComponent(raw); } catch { /* Keep malformed route text readable. */ }
  const [period, setPeriod] = useState("3m");
  const [metric, setMetric] = useState<Metric>("e1rm");
  const [data, setData] = useState<ExerciseDetail | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [details, setDetails] = useState(false);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    setData(null);
    api.strengthExercise(name, period).then((value) => { if (active) setData(value); })
      .catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [name, period]);
  const series = data?.series ?? [];
  const last = series.at(-1);
  const stats = data?.stats;
  const selected = METRICS[metric];
  const delta = data?.deltas?.[metric];
  const changeColor = metric === "e1rm" && delta != null && delta !== 0 ? (delta > 0 ? "text-good" : "text-bad") : "text-muted";

  return <>
    <header className="mb-5">
      <Link href="/kraft" className="text-xs font-semibold text-accent hover:underline">← Kraft</Link>
      <h1 className="mt-1 break-words font-display text-2xl font-extrabold tracking-tight">{name}</h1>
      <p className="mt-1 text-sm text-muted">{data?.muscle ? `${data.muscle} · ` : ""}Entwicklung je Trainingstag</p>
    </header>
    <div className="mb-4 flex flex-wrap gap-1" aria-label="Zeitraum">
      {PERIODS.map(([key, label]) => <button key={key} type="button" aria-pressed={period === key} onClick={() => setPeriod(key)} className={`rounded border px-3 py-2 text-xs font-semibold ${period === key ? "border-accent bg-accent text-white" : "border-line text-muted"}`}>{label}</button>)}
    </div>
    <Card>
      <div className="mb-4 flex flex-wrap gap-2" aria-label="Messgröße">
        {Object.entries(METRICS).map(([key, value]) => <button key={key} type="button" aria-pressed={metric === key} onClick={() => setMetric(key as Metric)} className={`rounded border px-3 py-2 text-xs ${metric === key ? "border-accent bg-accent/5 text-accent" : "border-line text-muted"}`}>{value.label}</button>)}
      </div>
      {loading ? <p className="py-6 text-sm text-muted" role="status">Wird geladen …</p> : error ? <p className="py-6 text-sm text-muted" role="status">Daten konnten nicht geladen werden. Wähle einen Zeitraum, um es erneut zu versuchen.</p> : !last || !stats ? <p className="py-6 text-sm text-muted">Keine Arbeitssätze in diesem Zeitraum. Über „Gesamt“ ist die ältere Historie erreichbar.</p> : <>
        <h2 className="text-sm font-semibold">{selected.label}</h2>
        <div className="mt-2 flex flex-wrap items-baseline gap-2 tabular-nums"><strong className="font-display text-3xl">{de(last[metric], metric === "tonnage" ? 0 : 1)}</strong><span className="text-sm text-muted">{selected.unit}</span></div>
        <p className="mt-1 text-xs text-muted">Letzter Trainingstag: {new Date(`${last.date}T12:00:00`).toLocaleDateString("de-DE")}{last[metric] == null ? " · keine Angabe" : ""}</p>
        <p className={`mt-2 text-xs ${changeColor}`}>{delta == null ? (series.length < 2 ? "Noch kein Vergleich: erst ein Trainingstag im Zeitraum." : "Kein Vergleich: am ersten oder letzten Trainingstag fehlt eine Angabe.") : `${delta > 0 ? "+" : ""}${de(delta, metric === "tonnage" ? 0 : 1)} ${selected.unit} · erster → letzter Trainingstag (${dm(series[0].date)}–${dm(last.date)})`}</p>
        <RunTrendChart key={`${metric}-${period}`} label={selected.label} unit={selected.unit} points={series.map((point) => ({ date: point.date, value: point[metric], detail: `${point.sets} Arbeitssätze · ${point.reps} Wiederholungen` }))} />
        <p className="mt-2 text-xs text-muted">{selected.note}</p>
        <button type="button" className="mt-4 rounded border border-line px-3 py-2 text-sm" onClick={() => setDetails(true)}>Bestleistungen & Details</button>
      </>}
    </Card>
    {details && stats && <RunAnalysisDialog title="Bestleistungen & Details" onClose={() => setDetails(false)}>
      <p className="mb-4 text-xs text-muted">Gewählter Zeitraum: {dm(stats.first_date)}–{dm(stats.last_date)} · {stats.sessions} Trainingstage · {stats.sets} Arbeitssätze</p>
      <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
        <div><dt className="text-xs text-muted">Bestes geschätztes 1RM</dt><dd className="mt-1 font-semibold">{de(stats.best_e1rm, 1)} kg · {dm(stats.best_e1rm_date)}</dd><dd className="text-xs text-muted">Zugehöriger Satz: {stats.best_set}</dd></div>
        <div><dt className="text-xs text-muted">Schwerster Arbeitssatz</dt><dd className="mt-1 font-semibold">{de(stats.top_weight, 1)} kg</dd></div>
        <div><dt className="text-xs text-muted">Bewegte Last gesamt</dt><dd className="mt-1 font-semibold">{de(stats.tonnage_kg / 1000, 1)} t</dd></div>
        <div><dt className="text-xs text-muted">Mittlere erfasste Anstrengung</dt><dd className="mt-1 font-semibold">{de(stats.avg_rpe, 1)} RPE</dd></div>
        <div><dt className="text-xs text-muted">Wiederholungen je Satz</dt><dd className="mt-1 font-semibold">Ø {de(stats.avg_reps, 1)}</dd></div>
      </dl>
      {data?.status && <section className="mt-5 border-t border-line pt-4 text-xs text-muted"><h3 className="font-semibold text-ink">Jüngste Entwicklung · unabhängig vom gewählten Zeitraum</h3><p className="mt-2">{data.status.label}: {data.status.detail}</p><p className="mt-2">Beschreibt die zuletzt erfassten Trainingstage. Daraus folgt weder eine Ermüdungsdiagnose noch eine Empfehlung für eine Trainingspause.</p></section>}
    </RunAnalysisDialog>}
  </>;
}
