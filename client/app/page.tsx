"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  api,
  type Overview, type WeightPoint, type WeekCompare,
  type StepsSummary, type Activity, type Report, type HealthOverview, type PR, type Consistency,
} from "@/lib/api";
import { Card, CardTitle, Kpi, PageTitle, StatRow, Loading, ApiError } from "@/components/ui";
import { AreaTrend } from "@/components/charts";
import { Heatmap } from "@/components/Heatmap";
import { de, de0, pace, dm, isToday } from "@/lib/format";

const COMPOUND = /squat|kniebeuge|bench|bankdr|deadlift|kreuzheb|press|drücken/i;
const mean = (a: number[]) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);

function Compare({ label, value, unit, delta, fmt, goodUp = true }:
  { label: string; value: string; unit?: string; delta: number | null; fmt: (n: number) => string; goodUp?: boolean }) {
  const up = (delta ?? 0) > 0;
  const flat = delta == null || delta === 0;
  const good = goodUp ? up : !up;
  return (
    <div>
      <div className="text-[11px] text-muted">{label}</div>
      <div className="mt-0.5 font-display text-xl font-bold tracking-tight">
        {value}{unit && <span className="ml-1 text-xs font-semibold text-muted">{unit}</span>}
      </div>
      <div className={`text-xs font-bold ${flat ? "text-muted" : good ? "text-good" : "text-bad"}`}>
        {flat ? "±0" : `${up ? "▲" : "▼"} ${fmt(Math.abs(delta!))}`} <span className="hidden font-normal text-muted sm:inline">vs. 7 T davor</span>
      </div>
    </div>
  );
}

export default function Overview() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [weight, setWeight] = useState<WeightPoint[]>([]);
  const [cmp, setCmp] = useState<WeekCompare | null>(null);
  const [steps, setSteps] = useState<StepsSummary | null>(null);
  const [health, setHealth] = useState<HealthOverview | null>(null);
  const [acts, setActs] = useState<Activity[]>([]);
  const [prs, setPrs] = useState<PR[]>([]);
  const [cons, setCons] = useState<Consistency | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.overview().then(setOv).catch((e) => setErr(String(e)));
    api.bodyWeight(120).then(setWeight).catch(() => {});
    api.activityCompare(7).then(setCmp).catch(() => {});
    api.bodySteps(14).then(setSteps).catch(() => {});
    api.healthOverview().then(setHealth).catch(() => {});
    api.activityRecent(6).then(setActs).catch(() => {});
    api.strengthRecords(120, 6).then(setPrs).catch(() => {});
    api.activityConsistency(365).then(setCons).catch(() => {});
    api.coachReports(1).then((r) => setReport(r[0] ?? null)).catch(() => {});
  }, []);

  if (err) return (<><PageTitle title="Übersicht" /><ApiError error={err} /></>);
  if (!ov) return (<><PageTitle title="Übersicht" /><Loading /></>);

  const { body: b, running: r, strength: s } = ov;
  const compounds = (s.main_lifts ?? []).filter((l) => COMPOUND.test(l.exercise));
  const feat = compounds.length ? compounds.reduce((a, c) => (c.e1rm > a.e1rm ? c : a)) : s.main_lifts?.[0] ?? null;
  const losing = (b.weight_delta7 ?? 0) <= 0;

  // Letzte 7 Tage vs. die 7 Tage davor (rollend, fairer als laufende Kalenderwoche)
  const kmNow = cmp?.running.current_km ?? null, kmPrev = cmp?.running.previous_km ?? null;
  const tNow = (cmp?.strength.current_kg ?? 0) / 1000, tPrev = cmp ? cmp.strength.previous_kg / 1000 : null;
  const stepDays = (steps?.series ?? []).map((p) => p.steps);
  const stepNow = stepDays.length >= 1 ? mean(stepDays.slice(-7)) : null;
  const stepPrev = stepDays.length > 7 ? mean(stepDays.slice(-14, -7)) : null;

  return (
    <>
      <PageTitle title="Übersicht" sub="Wo werde ich besser, wo schlechter?" />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Kpi
          label="Körper" sub="Gewicht & TDEE" watermark="/img/koerper-ink-arc.png"
          value={de(b.weight_kg, 1)} unit="kg"
          delta={`${losing ? "▼" : "▲"} ${de(Math.abs(b.weight_delta7 ?? 0), 2)} kg / 7 T`}
          deltaKind={losing ? "good" : "bad"}
        >
          <StatRow items={[["TDEE", `${de0(b.tdee)} kcal`], ["KFA", `${de(b.body_fat_pct, 1)} %`]]} />
        </Kpi>

        <Kpi
          label="Laufen" sub="Volumen & Tempo" watermark="/img/run-teal-solid.png"
          value={de(r.week_km, 1)} unit="km/Wo"
          delta={`${de0(r.week_runs)} Läufe`} deltaKind="muted"
        >
          <StatRow items={[["Pace", `${pace(r.pace)} /km`], ["VO₂max", de0(r.vo2max)]]} />
        </Kpi>

        <Kpi
          label="Kraft" sub={feat ? feat.exercise : "Kraftaufbau"} watermark="/img/kraft-ink-slash.png"
          value={de0(feat?.e1rm)} unit="kg e1RM"
          delta={`Tonnage ${de((s.week_tonnage_kg ?? 0) / 1000, 1)} t`} deltaKind="muted"
        >
          <StatRow items={[["RPE Ø", de(s.rpe, 1)], ["Peak", `${de0(feat?.peak)} kg`]]} />
        </Kpi>
      </div>

      <Card className="mt-4">
        <CardTitle title="Letzte 7 Tage" sub="rollend vs. die 7 Tage davor" />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Compare label="Laufvolumen" value={de(kmNow ?? 0, 1)} unit="km" goodUp
            delta={kmNow != null && kmPrev != null ? kmNow - kmPrev : null} fmt={(n) => `${de(n, 1)} km`} />
          <Compare label="Kraft-Tonnage" value={de(tNow, 1)} unit="t" goodUp
            delta={tPrev != null ? tNow - tPrev : null} fmt={(n) => `${de(n, 1)} t`} />
          <Compare label="Schritte Ø/Tag" value={stepNow != null ? de0(stepNow) : "–"} goodUp
            delta={stepNow != null && stepPrev != null ? stepNow - stepPrev : null} fmt={(n) => de0(n)} />
          <Compare label="Gewicht (7-T)" value={de(b.weight_avg7, 1)} unit="kg" goodUp={false}
            delta={b.weight_delta7 ?? null} fmt={(n) => `${de(n, 2)} kg`} />
        </div>
      </Card>

      {cons && cons.days.length > 0 && (
        <Card className="mt-4">
          <div className="mb-3 flex items-start justify-between gap-3">
            <CardTitle title="Konsistenz" sub={`${cons.total} Tage · Kraft/Lauf + Schritte`} />
            <div className="shrink-0 text-right">
              <div className="font-display text-2xl font-extrabold tracking-tight text-accent">🔥 {cons.streak}</div>
              <div className="text-[10px] text-muted">Tage-Streak</div>
            </div>
          </div>
          <Heatmap days={cons.days} />
          <div className="mt-2 text-[11px] text-muted">{cons.trained_days} Trainingstage · {cons.active_days} aktive Tage (von {cons.total})</div>
        </Card>
      )}

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card className="md:col-span-2">
          <CardTitle title="Gewicht · 120 Tage" sub="7-Tage-EWMA · Defizit greift, Wasser-Rauschen gefiltert" />
          <AreaTrend values={weight.map((w) => w.ewma)} labels={weight.map((w) => dm(w.date))} unit="kg" height={170} />
        </Card>

        <Card>
          <CardTitle title="Letzte Aktivitäten" />
          {acts.length === 0 ? (
            <p className="text-sm text-muted">Keine Aktivitäten.</p>
          ) : (
            <ul className="divide-y divide-line">
              {acts.map((a, i) => (
                <li key={i} className="flex items-center gap-2.5 py-2">
                  <span className="text-base">{a.kind === "run" ? "🏃" : "🏋️"}</span>
                  <span className="min-w-0 flex-1 truncate text-sm">{a.title}</span>
                  <span className="shrink-0 text-xs text-muted">{a.detail}</span>
                  <span className="w-12 shrink-0 text-right text-[11px] text-muted">{dm(a.date)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card className="flex flex-col md:col-span-2">
          <CardTitle title="Coach" sub={report ? `${report.kind} · ${dm(report.created_at)}` : "ehrlich-motivierend"} />
          <p className="flex-1 text-sm leading-relaxed text-muted">
            {report
              ? report.content.replace(/[#*`>|]/g, "").replace(/\s+/g, " ").trim().slice(0, 260) + " …"
              : "Tagesform, Trends und eine konkrete Anpassung – auf Basis deiner echten Zahlen."}
          </p>
          <Link href="/coach" className="mt-3 inline-flex w-fit items-center justify-center rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white hover:brightness-110">
            {report ? "Im Coach öffnen" : "Coach-Report erstellen"}
          </Link>
        </Card>

        <Card>
          <CardTitle title="Gesundheit" sub="Schritte & Radfahren" />
          <StatRow items={[[isToday(steps?.last_day) ? "Schritte heute" : "Schritte zuletzt", steps?.last != null ? de0(steps.last) : "–"], ["Ø 7 T", steps?.avg7 != null ? de0(steps.avg7) : "–"]]} />
          <StatRow items={[["Rad gesamt", health ? `${de(health.cycling.total_km, 0)} km` : "–"], ["Ø Tempo", health?.cycling.avg_speed != null ? `${de(health.cycling.avg_speed, 1)} km/h` : "–"]]} />
          <Link href="/gesundheit" className="mt-3 inline-flex w-fit items-center text-xs font-semibold text-accent hover:underline">
            Details →
          </Link>
        </Card>
      </div>

      {prs.length > 0 && (
        <Card className="mt-4">
          <CardTitle title="Neue Bestleistungen" sub="letzte Rekorde je Übung · e1RM oder Top-Gewicht" />
          <ul className="divide-y divide-line">
            {prs.map((p, i) => (
              <li key={i}>
                <Link href={`/kraft/${encodeURIComponent(p.exercise)}`} className="-mx-2 flex items-center gap-2.5 rounded-lg px-2 py-2 hover:bg-surface-alt">
                  <span className="text-base">🏆</span>
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold">{p.exercise}</span>
                  <span className="shrink-0 text-xs text-muted">{de0(p.e1rm)} kg e1RM · {de0(p.top_weight)} kg</span>
                  <span className="w-12 shrink-0 text-right text-[11px] text-muted">{dm(p.date)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
