"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { api, type BodySummary, type StandardizedHr, type RunningFitnessData, type StrengthIndex, type ActivityOverview, type Activity, type Report, type Consistency } from "@/lib/api";
import { Card, CardTitle, PageTitle } from "@/components/ui";
import { Heatmap } from "@/components/Heatmap";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
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
const loadConsistency = () => api.activityConsistency(84);
const loadYear = () => api.activityConsistency(365);
const loadActivities = () => api.activityRecent(5);
const loadReport = () => api.coachReports(1);
const signed = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? "Kein Vergleich verfügbar" : `${value > 0 ? "+" : value === 0 ? "±" : ""}${de(value, digits)}`;
const stamp = (date: string) => Date.parse(`${date.slice(0, 10)}T12:00:00Z`);

function StateNote({ resource, empty = "Noch keine Daten verfügbar." }: { resource: Resource<unknown>; empty?: string }) {
  return <p className="mt-3 text-xs text-muted" role="status">{resource.loading ? "Wird geladen …" : resource.error ? "Daten konnten nicht geladen werden. Bitte Seite neu laden." : empty}</p>;
}
function DevelopmentCard({ title, subtitle, href, children }: { title: string; subtitle: string; href: string; children: ReactNode }) {
  return <Card className="flex h-full min-w-0 flex-col"><h2 className="text-sm font-semibold">{title}</h2><p className="mt-1 text-xs text-muted">{subtitle}</p><div className="flex-1">{children}</div><Link href={href} className="mt-4 w-fit py-1 text-xs font-semibold text-accent">{title} ansehen →</Link></Card>;
}
function AnnualConsistency() {
  const resource = useResource<Consistency>(loadYear);
  return resource.data ? <><Heatmap days={resource.data.days} /><p className="mt-3 text-xs text-muted">{resource.data.trained_days} Trainingstage · {resource.data.active_days} aktive Tage · letzte 365 Tage</p></> : <StateNote resource={resource} />;
}
function ActivityValue({ label, value, unit, change, note, href }: { label: string; value: string; unit: string; change: string; note?: string; href: string }) {
  return <div className="min-w-0"><Link href={href} className="text-xs text-muted hover:underline">{label}</Link><p className="mt-1 font-display text-xl font-bold sm:text-2xl">{value} <span className="text-xs font-normal text-muted">{unit}</span></p><p className="mt-1 text-xs text-muted">{change}</p>{note && <p className="mt-1 text-[11px] text-muted">{note}</p>}</div>;
}

export default function Overview() {
  const body = useResource<BodySummary>(api.bodySummary);
  const running = useResource<StandardizedHr>(api.runStandardizedHr);
  const fitness = useResource<RunningFitnessData>(api.runFitness);
  const strength = useResource<StrengthIndex>(loadStrength);
  const activity = useResource<ActivityOverview>(api.activityOverview);
  const consistency = useResource<Consistency>(loadConsistency);
  const activities = useResource<Activity[]>(loadActivities);
  const reports = useResource<Report[]>(loadReport);
  const [yearOpen, setYearOpen] = useState(false);

  const b = body.data;
  const runPoints = running.data?.pace_series?.find((s) => s.pace_seconds === 360)?.points ?? [];
  const run = runPoints.filter((p) => p.hr != null).at(-1);
  const currentRun = runPoints.at(-1);
  // Compare only supported points from the same sensor segment near eight weeks earlier.
  const priorRun = run ? runPoints.filter((p) => p.hr != null && p.segment_id === run.segment_id && stamp(p.month) <= stamp(run.month) - 56 * 86400000 && stamp(p.month) >= stamp(run.month) - 63 * 86400000).at(-1) : null;
  const vo2 = fitness.data?.points?.filter((p) => p.vo2_eq != null).at(-1);
  const index = strength.data;
  const lastStrength = index?.series?.at(-1)?.week;
  const a = activity.data;
  const c = consistency.data;
  const report = reports.data?.[0];
  const excerpt = report?.content.replace(/[#*`>|]/g, "").replace(/\s+/g, " ").trim() ?? "";
  const stepsComparable = a?.steps.current_days === 7 && a?.steps.previous_days === 7;

  return <>
    <PageTitle title="Übersicht" sub="Deine Entwicklung auf einen Blick" />
    <div className="grid gap-4 md:grid-cols-3">
      <DevelopmentCard title="Körper" subtitle="Gewicht · 7-Tage-Mittel" href="/koerper">
        {b?.weight_avg7 != null ? <>
          <p className="mt-3 font-display text-3xl font-extrabold">{de(b.weight_avg7, 1)} <span className="text-sm font-normal text-muted">kg</span></p>
          <p className="mt-2 text-sm">{b.weight_delta7 == null ? "Kein Vergleich verfügbar" : `${signed(b.weight_delta7, 2)} kg gegenüber 7 Tagen zuvor`}</p>
          <p className="mt-2 text-xs text-muted">{b.weight_date ? `Stand ${dm(b.weight_date)}` : "Messdatum nicht verfügbar"} · {b.weight_days7}/7 Messtage</p>
          {b.weight_delta7 != null && b.previous_weight_days7 < 7 && <p className="mt-1 text-xs text-muted">Vorheriges Fenster: {b.previous_weight_days7}/7 Messtage</p>}
          <p className="mt-2 text-xs text-muted">Neutral bewertet · Körperziel noch offen</p>
        </> : <StateNote resource={body} />}
      </DevelopmentCard>
      <DevelopmentCard title="Laufen" subtitle="Puls bei 6:00 /km · Laufminute 30" href="/laufen">
        {run ? <>
          <p className="mt-3 font-display text-3xl font-extrabold">{de(run.hr, 1)} <span className="text-sm font-normal text-muted">bpm</span></p>
          <p className="mt-2 text-sm">{priorRun ? `${signed(run.hr! - priorRun.hr!, 1)} bpm seit ${dm(priorRun.month)}` : "Kein Vergleich vor 8 Wochen verfügbar"}</p>
          <p className="mt-2 text-xs text-muted">Stand {dm(run.month)} · {run.runs} Läufe</p>
          <p className="mt-2 text-xs text-muted">Niedriger = höhere Effizienz · geschätzter Verlauf</p>
          {run.status === "sensitive" && <p className="mt-1 text-xs text-muted">Empfindlich gegenüber einzelnen Läufen</p>}
          {currentRun?.hr == null && <p className="mt-1 text-xs text-muted">Aktuell nicht auswertbar; letzter verfügbarer Wert.</p>}
        </> : <StateNote resource={running} empty="Noch keine ausreichend gestützte Schätzung bei 6:00 /km." />}
        {vo2 ? <p className="mt-3 border-t border-line pt-2 text-xs text-muted">Eigenes VO₂eq: {de(vo2.vo2_eq, 1)} ml/kg/min · vorläufige Schätzung, {dm(vo2.date)}</p> : <StateNote resource={fitness} empty="Eigenes VO₂-Äquivalent noch nicht verfügbar." />}
      </DevelopmentCard>
      <DevelopmentCard title="Kraft" subtitle="Gesamtstärke · Basis 100 = Trainingsstart" href="/kraft">
        {index?.value != null ? <>
          <p className="mt-3 font-display text-3xl font-extrabold">{de0(index.value)} <span className="text-sm font-normal text-muted">Index</span></p>
          <p className="mt-2 text-sm">{index.window_delta_pct == null ? "Kein Vergleich verfügbar" : `${signed(index.window_delta_pct, 1)} % im 3-Monats-Vergleich`}</p>
          <p className="mt-2 text-xs text-muted">{lastStrength ? `Daten bis Woche vom ${dm(lastStrength)}` : "Datenstand nicht verfügbar"}</p>
          <p className="mt-2 text-xs text-muted">{index.cohort_size} Übungen · {index.groups} Muskelgruppen</p>
        </> : <StateNote resource={strength} empty="Noch nicht genügend vergleichbare Kraftdaten." />}
      </DevelopmentCard>
    </div>

    <Card className="mt-4">
      <CardTitle title="Aktivität" sub={a ? `${dm(a.from_date)}–${dm(a.to_date)} · Vergleich mit ${dm(a.previous_from_date)}–${dm(a.previous_to_date)} · heute noch unvollständig` : "Letzte 7 Kalendertage gegenüber den 7 Tagen davor"} />
      {a ? <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <ActivityValue label="Laufkilometer" value={de(a.running.current_km, 1)} unit="km" change={`${signed(a.running.current_km - a.running.previous_km, 1)} km`} href="/laufen" />
        <ActivityValue label="Krafttraining" value={de0(a.strength.current_sessions)} unit="Einheiten" change={`${signed(a.strength.current_sessions - a.strength.previous_sessions, 0)} Einheiten`} href="/kraft" />
        <ActivityValue label="Schritte pro erfasstem Tag" value={de0(a.steps.current_avg)} unit="Schritte" change={stepsComparable && a.steps.current_avg != null && a.steps.previous_avg != null ? `${signed(a.steps.current_avg - a.steps.previous_avg, 0)} Schritte` : "Kein vollständiger Vergleich"} note={`${a.steps.current_days}/7 Tage erfasst · davor ${a.steps.previous_days}/7`} href="/gesundheit" />
      </div> : <StateNote resource={activity} />}
    </Card>

    <Card className="mt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <CardTitle title="Konsistenz" sub="Letzte 12 Wochen · Training und Schritte" />
        {c && <p className="text-sm"><strong>{c.streak >= c.total - (c.days.at(-1)?.level === 0 ? 1 : 0) ? "≥ " : ""}{c.streak}</strong> <span className="text-xs text-muted">Tage aktive Serie</span></p>}
      </div>
      {c ? <><Heatmap days={c.days} /><p className="mt-3 text-xs text-muted">{c.trained_days} Trainingstage · {c.active_days} aktive Tage · aktiv ab Training oder {de0(c.step_goal / 2)} Schritten</p><button className="mt-3 py-1 text-xs font-semibold text-accent" onClick={() => setYearOpen(true)}>Ganzes Jahr ansehen →</button></> : <StateNote resource={consistency} />}
    </Card>

    <div className="mt-4 grid gap-4 lg:grid-cols-2">
      <Card>
        <CardTitle title="Letzte Aktivitäten" />
        {activities.data?.length ? <ul className="divide-y divide-line">{activities.data.map((item, i) => <li key={`${item.date}:${i}`}><Link href={item.kind === "run" ? "/laufen" : "/kraft"} className="flex items-center gap-3 py-3 text-sm"><span className="min-w-0 flex-1"><span className="block truncate font-semibold">{item.title}</span><span className="text-xs text-muted">{item.detail}</span></span><time className="shrink-0 text-xs text-muted" dateTime={item.date}>{dm(item.date)}</time></Link></li>)}</ul> : <StateNote resource={activities} empty="Noch keine Aktivitäten erfasst." />}
      </Card>
      <Card className="flex flex-col">
        <CardTitle title="Coach" sub={report ? `Letzter gespeicherter Beitrag · ${dm(report.created_at)}` : "Deine Daten gemeinsam einordnen"} />
        {report ? <p className="text-sm leading-relaxed text-muted">{excerpt.slice(0, 240)}{excerpt.length > 240 ? " …" : ""}</p> : <StateNote resource={reports} empty="Noch kein Coach-Beitrag vorhanden." />}
        <Link href="/coach" className="mt-4 w-fit rounded border border-line px-3 py-2 text-sm font-semibold text-accent">Coach öffnen →</Link>
      </Card>
    </div>
    {yearOpen && <RunAnalysisDialog title="Konsistenz · ganzes Jahr" onClose={() => setYearOpen(false)}><AnnualConsistency /></RunAnalysisDialog>}
  </>;
}
