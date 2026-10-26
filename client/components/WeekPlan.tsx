"use client";

import Link from "next/link";
import { useState } from "react";
import { api, bikeZwoUrl, type WeekColor, type WeekDay, type WeekItem, type WeekPlan } from "@/lib/api";
import { de, de0, dm } from "@/lib/format";
import { ExecutionLine, Warnings } from "@/components/BikePlan";

// Farben angelehnt an TrainingPeaks; Farbe steht nie allein, jede Einheit trägt auch ihren Text-Status.
export const WEEK_COLOR: Record<WeekColor, { bar: string; label: string }> = {
  green: { bar: "var(--color-good)", label: "im Soll" },
  yellow: { bar: "var(--color-warn)", label: "teilweise" },
  orange: { bar: "#c2410c", label: "deutlich daneben" },
  red: { bar: "var(--color-bad)", label: "verpasst" },
  grey: { bar: "#9aa5b1", label: "ungeplant" },
  open: { bar: "var(--color-line)", label: "offen" },
  skipped: { bar: "var(--color-line)", label: "ausgelassen (optional)" },
  sick: { bar: "var(--color-sick)", label: "krank (pausiert)" },
};
const TYPE_LABEL: Record<WeekItem["type"], string> = { bike: "Rad", gym: "Kraft", ride: "Rad", run: "Lauf", strength: "Kraft" };

function status(it: WeekItem): string {
  if (it.type === "bike") {
    if (it.status === "run") return "als Lauf";
    if (it.status === "done" && it.ratio != null) return `${de0(it.ratio * 100)} % der Dauer`;
    if (it.status === "done") return "erledigt";
  }
  if (it.type === "gym" && it.done) return it.color === "yellow" ? `${it.done.title} (anderes Programm)` : "erledigt";
  return WEEK_COLOR[it.color].label;
}

function Item({ it, planning, days, onMove }: { it: WeekItem; planning?: boolean; days?: WeekDay[]; onMove?: (it: WeekItem, to: string) => void }) {
  const movable = planning && it.planned && (it.type === "bike" || it.type === "gym") && it.color === "open";
  const c = WEEK_COLOR[it.color];
  const sub = it.type === "bike"
    ? [it.optional ? "optional" : null, it.duration_min ? `${de0(it.duration_min)} min` : null, it.target].filter(Boolean).join(" · ")
    : it.type === "gym" ? (it.label ?? "")
    : it.type === "run" ? `${de(it.km, 1)} km · ${de0(it.minutes)} min${it.avg_hr ? ` · Ø ${it.avg_hr} bpm` : ""}`
    : `${de0(it.minutes)} min`;
  const body = (
    <div className={`grid min-w-0 gap-1 rounded-md border bg-surface py-1.5 pl-2.5 pr-2 ${it.color === "open" ? "border-dashed border-line" : "border-line"}`}
      style={{ boxShadow: `inset 3px 0 0 ${c.bar}` }}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="min-w-0 truncate text-xs font-semibold"><span className="mr-1 text-[10px] font-normal uppercase tracking-wide text-muted">{TYPE_LABEL[it.type]}</span>{it.title}</span>
        <span className="shrink-0 text-[10px] font-semibold" style={{ color: it.color === "open" || it.color === "skipped" ? "var(--color-muted)" : it.color === "sick" ? "#5b3f8c" : c.bar }}>{it.hard ? "hart · " : ""}{status(it)}</span>
      </div>
      {movable && days && onMove && (
        <label className="flex items-center gap-1 text-[11px] text-muted">verschieben auf
          <select value="" onChange={(e) => e.target.value && onMove(it, e.target.value)} className="rounded border border-line bg-surface px-1 py-0.5 text-base sm:text-[11px]" aria-label={`${it.title} verschieben`}>
            <option value="">–</option>
            {days.filter((d) => !d.past && !d.items.some((x) => x === it)).map((d) => <option key={d.date} value={d.date}>{d.weekday} {dm(d.date)}</option>)}
          </select>
        </label>
      )}
      {sub && <p className="truncate text-[11px] text-muted">{sub}</p>}
      {it.type === "bike" && it.ride && <p className="truncate text-[11px] text-muted">gefahren: {de0(it.ride.minutes)} min{it.ride.np ? ` · NP ${de0(it.ride.np)} W` : ""}{it.ride.avg_hr ? ` · Ø ${de0(it.ride.avg_hr)} bpm` : ""}</p>}
      {it.type === "bike" && it.execution && <ExecutionLine ex={it.execution} />}
      {it.type === "bike" && (it.status === "today" || it.status === "planned") && it.run_alternative && <p className="text-[11px] text-muted">oder Lauf: {it.run_alternative}</p>}
      {it.warnings?.length ? <Warnings items={it.warnings} /> : null}
      {it.prescription?.length ? (
        <details className="text-[11px]">
          <summary className="cursor-pointer text-muted">Gewichte für {it.title}</summary>
          <ul className="mt-1 space-y-0.5 tabular-nums">{it.prescription.map((p) => <li key={p}>{p}</li>)}</ul>
        </details>
      ) : null}
      {it.zwo && (it.status === "today" || it.status === "planned") ? <a href={bikeZwoUrl(it.zwo)} download className="text-[11px] font-semibold text-accent underline underline-offset-4">Zwift-Workout (.zwo)</a> : null}
    </div>
  );
  if (movable) {
    return <div draggable className="cursor-grab" onDragStart={(e) => e.dataTransfer.setData("text/plain", JSON.stringify({ type: it.type, id: it.session_id, day: it.day }))}>{body}</div>;
  }
  return it.href && !it.prescription?.length && !it.zwo && it.type !== "bike" ? <Link href={it.href} className="block">{body}</Link> : body;
}

function DayContext({ d }: { d: WeekDay }) {
  const w = d.context.weather;
  const parts = [
    d.context.sick ? "krank" : null,
    d.context.sleep_h != null ? `Schlaf ${de(d.context.sleep_h, 1)} h` : null,
    d.context.energy != null ? `Energie ${d.context.energy}/5` : null,
    w ? `${w.label ?? ""} ${de0(w.temp_min)}–${de0(w.temp_max)} °C${w.rain_prob != null ? ` · Regen ${w.rain_prob} %` : ""}` : null,
  ].filter(Boolean);
  return (
    <div className="grid gap-0.5 text-[11px] text-muted">
      {parts.length > 0 && <p className={d.context.sick ? "font-semibold text-[#5b3f8c]" : ""}>{parts.join(" · ")}</p>}
      {w?.run && !d.past && <p>Laufwetter: {w.run.start.slice(11, 16)}–{w.run.end.slice(11, 16)}{w.run.clothing ? ` · ${w.run.clothing}` : ""}</p>}
    </div>
  );
}

export function WeekDays({ data, planning = false, onChanged }: { data: WeekPlan; planning?: boolean; onChanged?: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const run = async (p: Promise<unknown>) => {
    try { await p; setErr(null); onChanged?.(); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  const move = (it: WeekItem, to: string) => {
    if (it.type === "bike" && it.session_id) run(api.bikePlanSessionUpdate(it.session_id, { day: to }));
    if (it.type === "gym" && it.day) run(api.weekGymMove(it.day, to));
  };
  const drop = (raw: string, to: string) => {
    try {
      const m = JSON.parse(raw) as { type: string; id?: number; day?: string };
      if (m.type === "bike" && m.id) run(api.bikePlanSessionUpdate(m.id, { day: to }));
      if (m.type === "gym" && m.day && m.day !== to) run(api.weekGymMove(m.day, to));
    } catch { /* fremder Inhalt */ }
  };
  return (
    <ol className="grid gap-2" aria-label="Tage der Woche">
      {err && <li role="alert" className="text-xs text-bad">{err}</li>}
      {data.days.map((d) => (
        <li key={d.date}
          onDragOver={planning && !d.past ? (e) => { e.preventDefault(); setOver(d.date); } : undefined}
          onDragLeave={planning ? () => setOver((o) => (o === d.date ? null : o)) : undefined}
          onDrop={planning && !d.past ? (e) => { e.preventDefault(); setOver(null); drop(e.dataTransfer.getData("text/plain"), d.date); } : undefined}
          className={`grid gap-2 rounded-lg border bg-surface p-3 sm:grid-cols-[5.5rem_minmax(0,1fr)] ${d.today ? "border-accent ring-1 ring-accent" : "border-line"} ${over === d.date ? "bg-accent/5" : ""}`}>
          <div className="flex items-baseline gap-2 sm:block">
            <p className="text-sm font-semibold">{d.weekday} <span className="font-normal text-muted">{dm(d.date)}</span></p>
            {d.today && <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-semibold text-white">heute</span>}
          </div>
          <div className="grid min-w-0 gap-2">
            <DayContext d={d} />
            {d.items.length ? <div className="grid gap-1.5 md:grid-cols-2">{d.items.map((it, i) => <Item key={i} it={it} planning={planning} days={data.days} onMove={move} />)}</div>
              : <p className="text-[11px] text-muted">Ruhetag</p>}
            {planning && !d.past && <GymPicker d={d} onSet={(p) => run(api.weekGym(d.date, p))} />}
          </div>
        </li>
      ))}
    </ol>
  );
}

function GymPicker({ d, onSet }: { d: WeekDay; onSet: (p: "ok" | "uk" | null) => void }) {
  const gym = d.items.find((i) => i.type === "gym");
  const value = gym?.program ?? "";
  return (
    <label className="flex items-center gap-1 text-[11px] text-muted">Kraft an diesem Tag
      <select value={value} onChange={(e) => onSet((e.target.value || null) as "ok" | "uk" | null)} className="rounded border border-line bg-surface px-1 py-0.5 text-base sm:text-[11px]" aria-label={`Kraft am ${dm(d.date)}`}>
        <option value="">kein Krafttraining</option><option value="ok">Milon OK</option><option value="uk">Milon UK</option>
      </select>
    </label>
  );
}

export function WeekLegend() {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted">
      {(["green", "yellow", "orange", "red", "grey", "sick", "open"] as WeekColor[]).map((k) => (
        <span key={k} className="flex items-center gap-1"><span className="inline-block h-2.5 w-1 rounded-sm" style={{ background: WEEK_COLOR[k].bar }} />{WEEK_COLOR[k].label}</span>
      ))}
      <span>· Rad im Soll = Dauer ±20 %</span>
    </div>
  );
}

// Kompakte Zeile für die Übersicht.
export function WeekLine({ data }: { data: WeekPlan }) {
  const t = data.totals;
  return (
    <p className="text-sm">
      <span className="font-semibold">Diese Woche:</span>{" "}
      <span className="text-muted">Rad {de0(t.bike_done_min)}/{de0(t.bike_planned_min)} min · Kraft {t.gym_matched}/{t.gym_planned} · harte Einheiten {t.hard_done}/{t.hard_planned}{t.run_km ? ` · Lauf ${de(t.run_km, 1)} km` : ""}</span>
    </p>
  );
}
