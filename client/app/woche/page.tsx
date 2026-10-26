"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type WeekPlan, type WeekToday } from "@/lib/api";
import { Kpi, Loading, ApiError, PageTitle } from "@/components/ui";
import { Warnings } from "@/components/BikePlan";
import { TodayHero, WeekDays, WeekLegend } from "@/components/WeekPlan";
import { WeeklyReview } from "@/components/WeeklyReview";
import { de, de0, dm } from "@/lib/format";

const SEGMENTS: [number, string, string][] = [[-1, "Vorwoche", "Vorwoche"], [0, "Diese Woche", "Diese"], [1, "Nächste Woche", "Nächste"]];

export default function Woche() {
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<WeekPlan | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [planning, setPlanning] = useState(false);
  const [revision, setRevision] = useState(0);
  const [today, setToday] = useState<WeekToday | null>(null);
  useEffect(() => { api.weekToday().then(setToday).catch(() => setToday(null)); }, [revision]);

  useEffect(() => {
    let alive = true;
    if (revision === 0) setData(null);
    setErr(null);
    api.week(offset).then((d) => { if (alive) setData(d); }).catch((e) => { if (alive) setErr(String(e)); });
    return () => { alive = false; };
  }, [offset, revision]);

  const t = data?.totals;
  const future = offset > 0;
  const sub = data ? `KW ${data.iso_week} · ${dm(data.from)}–${dm(data.to)}${data.plan ? ` · ${data.plan.name} Woche ${data.plan.week}${data.plan.phase ? ` (${data.plan.phase})` : ""}` : ""}` : "Rad, Kraft und Lauf an einem Ort";

  return <>
    <PageTitle title="Mein Wochenplan" sub={sub} />
    {today && <TodayHero data={today} />}

    <div className="mb-4 flex flex-wrap items-center gap-2">
      <button type="button" onClick={() => setOffset(offset - 1)} disabled={offset <= -52} aria-label="Woche zurück" className="rounded-md border border-line px-2 py-1 text-sm">‹</button>
      <div className="inline-flex overflow-hidden rounded-md border border-line" role="group" aria-label="Woche wählen">
        {SEGMENTS.map(([o, label, short]) => (
          <button key={o} type="button" aria-pressed={offset === o} onClick={() => setOffset(o)}
            className={`px-2.5 py-1 text-xs font-semibold sm:px-3 ${offset === o ? "bg-accent text-white" : "bg-surface text-ink"} ${o !== -1 ? "border-l border-line" : ""}`}><span className="sm:hidden">{short}</span><span className="hidden sm:inline">{label}</span></button>
        ))}
      </div>
      <button type="button" onClick={() => setOffset(offset + 1)} disabled={offset >= 8} aria-label="Woche vor" className="rounded-md border border-line px-2 py-1 text-sm">›</button>
      {offset !== 0 && SEGMENTS.every(([o]) => o !== offset) && <button type="button" onClick={() => setOffset(0)} className="text-xs text-accent underline underline-offset-4">Heute</button>}
    </div>

    {err ? <ApiError error={err} /> : !data || !t ? <Loading /> : <>
      {data.plan?.goal && <p className="-mt-2 mb-3 text-xs text-muted">Ziel der Woche: {data.plan.goal}</p>}
      <section aria-label="Wochensumme" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Rad" sub={future ? "geplant" : `erledigt · geplant ${de0(t.bike_planned_min)} min`} value={de0(future ? t.bike_planned_min : t.bike_done_min)} unit="min"
          delta={future ? `${t.bike_planned} Einheiten` : `${t.bike_matched}/${t.bike_planned} Plan-Einheiten · ${t.bike_done} ${t.bike_done === 1 ? "Fahrt" : "Fahrten"}`} deltaKind="muted" />
        <Kpi label="Kraft" sub={future ? "geplant (OK/UK)" : "nach Plan erledigt"} value={future ? String(t.gym_planned) : `${t.gym_matched}/${t.gym_planned}`} unit="Einheiten"
          delta={data.hard_sets ? `harte Sätze ${de0(data.hard_sets.done)}/${de0(data.hard_sets.planned)}` : `${t.gym_done} Workouts`} deltaKind="muted" />
        <Kpi label="Harte Einheiten" sub={`Regel: höchstens ${data.max_hard} pro Woche`} value={future ? String(t.hard_planned) : `${t.hard_done}/${t.hard_planned}`} unit={future ? "geplant" : "erledigt"}
          delta={t.hard_planned > data.max_hard ? "über der Regel" : undefined} deltaKind="bad" />
        <Kpi label="Lauf & Form" sub={data.form ? `Form am ${dm(data.form.date)}` : "ohne Puls-Last"} value={data.form ? de0(data.form.tsb) : "–"} unit="TSB"
          delta={`${de(t.run_km, 1)} km in ${t.runs} ${t.runs === 1 ? "Lauf" : "Läufen"}`} deltaKind="muted" />
      </section>

      {data.warnings.length > 0 && <div className="mt-3"><Warnings items={data.warnings} /></div>}
      <div className="mb-2 mt-4 flex flex-wrap items-baseline justify-between gap-2">
        <WeekLegend />
        <span className="flex items-center gap-3 text-xs">
          {offset >= 0 && <button type="button" aria-pressed={planning} onClick={() => setPlanning(!planning)}
            className={`rounded-md border px-3 py-1 font-semibold ${planning ? "border-accent bg-accent text-white" : "border-accent text-accent"}`}>{planning ? "Fertig" : "Planen"}</button>}
          <Link href="/rad/plan" className="text-accent">Rad-Plan →</Link><Link href="/kraft" className="text-accent">Kraft →</Link>
        </span>
      </div>
      {planning && offset >= 0 && <p className="mb-2 text-[11px] text-muted">Offene Einheiten auf einen anderen Tag ziehen oder per „verschieben auf“ umlegen (belegter Tag = tauschen); Kraft je Tag festlegen. Hinweise zu den Regeln aktualisieren sich sofort.</p>}
      <WeekDays data={data} planning={planning && offset >= 0} onChanged={() => setRevision((r) => r + 1)} />
    </>}

    <div className="mt-6"><WeeklyReview /></div>
  </>;
}
