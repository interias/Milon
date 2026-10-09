"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { api, type BodySummary, type StandardizedHr, type RunningFitnessData, type StrengthIndex, type Report, type Consistency } from "@/lib/api";
import { Card, CardTitle, PageTitle } from "@/components/ui";
import { Heatmap } from "@/components/Heatmap";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { CheckIn, CHECKINS_CHANGED } from "@/components/CheckIn";
import { WeatherCard } from "@/components/WeatherCard";
import { WeeklyReview } from "@/components/WeeklyReview";
import { OverviewHistory, HistoryCards } from "@/components/OverviewHistory";
import type { HistoryPoint } from "@/lib/overview-history";
import { de, de0, dm } from "@/lib/format";

type Resource<T> = { data: T | null; loading: boolean; error: boolean };
function useResource<T>(load: () => Promise<T>): Resource<T> {
  const [state, setState] = useState<Resource<T>>({ data: null, loading: true, error: false });
  useEffect(() => {
    let active = true;
    load().then((data) => { if (active) setState({ data, loading: false, error: false }); })
      .catch(() => { if (active) setState({ data: null, loading: false, error: true }); });
    return () => { active = false; };
  }, [load]);
  return state;
}
const loadStrength = () => api.strengthIndex("3m");
const loadReport = () => api.coachReports(1);
const signed = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? "Kein Vergleich verfügbar" : `${value > 0 ? "+" : value === 0 ? "±" : ""}${de(value, digits)}`;
const stamp = (date: string) => Date.parse(`${date.slice(0, 10)}T12:00:00Z`);

function StateNote({ resource, empty = "Noch keine Daten verfügbar." }: { resource: Resource<unknown>; empty?: string }) {
  return <p className="mt-3 text-xs text-muted" role="status">{resource.loading ? "Wird geladen …" : resource.error ? "Daten konnten nicht geladen werden. Bitte Seite neu laden." : empty}</p>;
}
function SickDaysForm({ onDone }: { onDone: () => void }) {
  const today = new Date().toLocaleDateString("sv-SE");
  const [start, setStart] = useState(today);
  const [end, setEnd] = useState(today);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save(sick: boolean) {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "/api"}/checkins/sick`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ start, end, sick }),
      });
      if (!response.ok) throw new Error("Zeitraum ungültig (höchstens 93 Tage, nicht in der Zukunft).");
      window.dispatchEvent(new Event(CHECKINS_CHANGED));
      onDone();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  }
  const input = "rounded border border-line bg-surface px-2 py-1.5 text-base sm:text-sm";
  return <div className="mt-3 rounded-card border border-sick/50 bg-sick/10 p-3">
    <div className="flex flex-wrap items-end gap-3 text-xs">
      <label className="flex flex-col gap-1 text-muted">Krank von<input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} className={input} /></label>
      <label className="flex flex-col gap-1 text-muted">bis<input type="date" value={end} min={start} max={today} onChange={(e) => setEnd(e.target.value)} className={input} /></label>
      <button type="button" disabled={busy || !start || !end} onClick={() => void save(true)} className="rounded bg-[#5b3f8c] px-3 py-2 font-semibold text-white disabled:opacity-50">Eintragen</button>
      <button type="button" disabled={busy || !start || !end} onClick={() => void save(false)} className="py-2 text-muted underline underline-offset-4 disabled:opacity-50">Zeitraum entfernen</button>
      <button type="button" onClick={onDone} className="py-2 text-muted underline underline-offset-4">Abbrechen</button>
    </div>
    {error && <p role="alert" className="mt-2 text-xs text-bad">{error}</p>}
  </div>;
}
// Kompakte Kennzahl-Kachel: Hauptwert + Veränderung sichtbar, Nebeninfos unter „Details“.
function KpiTile({ title, subtitle, href, value, unit, change, meta, details = [], empty }: {
  title: string; subtitle: string; href: string; value: string | null; unit: string; change: ReactNode; meta: ReactNode;
  details?: ReactNode[]; empty: ReactNode;
}) {
  const shown = details.filter(Boolean);
  return <section className="flex min-w-0 flex-1 flex-col rounded-card border border-line bg-surface px-4 py-3 shadow-[0_1px_2px_rgba(20,32,31,0.04)]">
    <Link href={href} className="w-fit whitespace-nowrap text-sm font-semibold hover:text-accent">{title} <span className="text-accent">→</span></Link>
    <span className="truncate text-[11px] text-muted">{subtitle}</span>
    {value != null ? <>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-3">
        <p className="font-display text-2xl font-extrabold">{value} <span className="text-sm font-normal text-muted">{unit}</span></p>
        <p className="text-xs">{change}</p>
      </div>
      <p className="mt-0.5 text-[11px] text-muted">{meta}</p>
      {shown.length > 0 && <details className="mt-1 text-[11px] text-muted">
        <summary className="w-fit cursor-pointer select-none py-0.5 hover:text-accent">Details</summary>
        <div className="mt-1 space-y-0.5">{shown.map((item, i) => <p key={i}>{item}</p>)}</div>
      </details>}
    </> : empty}
  </section>;
}
function ConsistencyHistory({ data, fit = false }: { data: Consistency; fit?: boolean }) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState<number | null>(null);
  useEffect(() => {
    if (!fit || !container.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(container.current);
    return () => observer.disconnect();
  }, [fit]);
  const last = data.days.at(-1);
  const lastWeekday = last ? (new Date(last.date + "T00:00:00").getDay() + 6) % 7 : 0;
  // Each week occupies 12px plus a 3px gap; keep the latest partial week.
  const capacity = width == null ? 0 : (Math.max(1, Math.floor((width + 3) / 15)) - 1) * 7 + lastWeekday + 1;
  const days = fit ? (capacity ? data.days.slice(-capacity) : []) : data.days;
  return <div ref={container} className="min-w-0">
    <Heatmap days={days} />
    {days.length > 0 && <p className="mt-3 text-xs text-muted">{dm(days[0].date)}–{dm(days.at(-1)!.date)} · {days.filter((d) => d.trained).length} Trainingstage · {days.filter((d) => d.level >= 1).length} aktive Tage{days.some((d) => d.sick) ? ` · ${days.filter((d) => d.sick).length} Krankheitstage` : ""} · aktiv ab Training oder {de0(data.step_goal / 2)} Schritten</p>}
  </div>;
}

export default function Overview() {
  const body = useResource<BodySummary>(api.bodySummary);
  const running = useResource<StandardizedHr>(api.runStandardizedHr);
  const fitness = useResource<RunningFitnessData>(api.runFitness);
  const strength = useResource<StrengthIndex>(loadStrength);
  const [checkinRevision, setCheckinRevision] = useState(0);
  const loadConsistency = useCallback(() => api.activityConsistency(0), [checkinRevision]);
  const consistency = useResource<Consistency>(loadConsistency);
  const [sickOpen, setSickOpen] = useState(false);
  useEffect(() => {
    const bump = () => setCheckinRevision((n) => n + 1);
    window.addEventListener(CHECKINS_CHANGED, bump);
    return () => window.removeEventListener(CHECKINS_CHANGED, bump);
  }, []);
  const reports = useResource<Report[]>(loadReport);
  const [yearOpen, setYearOpen] = useState(false);
  const [historyPoint, setHistoryPoint] = useState<HistoryPoint | null>(null);

  const b = body.data;
  const runPoints = running.data?.pace_series?.find((s) => s.pace_seconds === 360)?.points ?? [];
  const run = runPoints.filter((p) => p.hr != null).at(-1);
  const currentRun = runPoints.at(-1);
  // Compare only supported points from the same sensor segment near eight weeks earlier.
  const priorRun = run ? runPoints.filter((p) => p.hr != null && p.segment_id === run.segment_id && stamp(p.month) <= stamp(run.month) - 56 * 86400000 && stamp(p.month) >= stamp(run.month) - 63 * 86400000).at(-1) : null;
  const vo2 = fitness.data?.points?.filter((p) => p.vo2_eq != null).at(-1);
  const index = strength.data;
  const lastStrength = index?.series?.at(-1)?.week;
  const c = consistency.data;
  const report = reports.data?.[0];
  const excerpt = report?.content.replace(/[#*`>|]/g, "").replace(/\s+/g, " ").trim() ?? "";

  return <>
    <PageTitle title="Übersicht" sub="Deine Entwicklung auf einen Blick" />
    <div className="grid gap-4 xl:grid-cols-3">
      <div className="min-w-0 xl:col-span-2"><WeatherCard /></div>
      <div className="grid min-w-0 gap-4 md:grid-cols-3 xl:flex xl:flex-col">
        <KpiTile title="Körper" subtitle="Gewicht · 7-Tage-Mittel" href="/koerper"
          value={b?.weight_avg7 != null ? de(b.weight_avg7, 1) : null} unit="kg"
          change={b?.weight_delta7 == null ? "Kein Vergleich" : `${signed(b.weight_delta7, 2)} kg ggü. 7 Tagen`}
          meta={<>{b?.weight_date ? `Stand ${dm(b.weight_date)}` : "Messdatum fehlt"} · {b?.weight_days7}/7 Messtage</>}
          details={[b?.weight_delta7 != null && b.previous_weight_days7 < 7 && `Vorheriges Fenster: ${b.previous_weight_days7}/7 Messtage`,
            "Neutral bewertet · Körperziel noch offen"]}
          empty={<StateNote resource={body} />} />
        <KpiTile title="Laufen" subtitle="Puls bei 6:00 /km · Minute 30" href="/laufen"
          value={run ? de(run.hr, 1) : null} unit="bpm"
          change={priorRun ? `${signed(run!.hr! - priorRun.hr!, 1)} bpm seit ${dm(priorRun.month)}` : "Kein Vergleich vor 8 Wochen"}
          meta={<>Stand {run ? dm(run.month) : "–"} · {run?.runs} Läufe{vo2 ? <> · VO₂eq {de(vo2.vo2_eq, 1)}</> : null}</>}
          details={["Niedriger = höhere Effizienz · geschätzter Verlauf",
            run?.status === "sensitive" && "Empfindlich gegenüber einzelnen Läufen",
            currentRun?.hr == null && "Aktuell nicht auswertbar; letzter verfügbarer Wert.",
            vo2 ? `Eigenes VO₂eq: ${de(vo2.vo2_eq, 1)} ml/kg/min · vorläufige Schätzung, ${dm(vo2.date)}` : "Eigenes VO₂-Äquivalent noch nicht verfügbar."]}
          empty={<StateNote resource={running} empty="Noch keine ausreichend gestützte Schätzung bei 6:00 /km." />} />
        <KpiTile title="Kraft" subtitle="Gesamtstärke · Basis 100" href="/kraft"
          value={index?.value != null ? de0(index.value) : null} unit="Index"
          change={index?.window_delta_pct == null ? "Kein Vergleich" : `${signed(index.window_delta_pct, 1)} % in 3 Monaten`}
          meta={<>{lastStrength ? `Bis Woche vom ${dm(lastStrength)}` : "Datenstand fehlt"} · {index?.cohort_size} Übungen</>}
          details={[`${index?.cohort_size} Übungen · ${index?.groups} Muskelgruppen`, "Basis 100 = Trainingsstart"]}
          empty={<StateNote resource={strength} empty="Noch nicht genügend vergleichbare Kraftdaten." />} />
      </div>
    </div>
    <CheckIn />

    <Card className="mt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <CardTitle title="Konsistenz" sub="Training und Schritte · Zeitraum passend zur verfügbaren Breite" />
        {c && <p className="text-sm"><strong>{c.streak >= c.total - (c.days.at(-1)?.level === 0 ? 1 : 0) ? "≥ " : ""}{c.streak}</strong> <span className="text-xs text-muted">Tage aktive Serie</span></p>}
      </div>
      {c ? <><ConsistencyHistory data={c} fit />
        <div className="mt-3 flex flex-wrap gap-x-5">
          <button className="py-1 text-xs font-semibold text-accent" onClick={() => setYearOpen(true)}>Gesamten Zeitraum ansehen →</button>
          {!sickOpen && <button className="py-1 text-xs font-semibold text-[#5b3f8c]" onClick={() => setSickOpen(true)}>Krankheitstage eintragen</button>}
        </div>
        {sickOpen && <SickDaysForm onDone={() => setSickOpen(false)} />}</> : <StateNote resource={consistency} />}
    </Card>

    <OverviewHistory onSelect={setHistoryPoint} />
    {historyPoint && <div className="mt-4"><HistoryCards point={historyPoint} /></div>}
    <WeeklyReview />

    <div className="mt-4">
      <Card className="flex flex-col">
        <CardTitle title="Coach" sub={report ? `Letzter gespeicherter Beitrag · ${dm(report.created_at)}` : "Deine Daten gemeinsam einordnen"} />
        {report ? <p className="text-sm leading-relaxed text-muted">{excerpt.slice(0, 240)}{excerpt.length > 240 ? " …" : ""}</p> : <StateNote resource={reports} empty="Noch kein Coach-Beitrag vorhanden." />}
        <Link href="/coach" className="mt-4 w-fit rounded border border-line px-3 py-2 text-sm font-semibold text-accent">Coach öffnen →</Link>
      </Card>
    </div>
    {yearOpen && c && <RunAnalysisDialog title="Konsistenz · gesamter Zeitraum" onClose={() => setYearOpen(false)}><ConsistencyHistory data={c} /></RunAnalysisDialog>}
  </>;
}
