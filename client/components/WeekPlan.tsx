"use client";

import Link from "next/link";
import { bikeZwoUrl, type WeekColor, type WeekDay, type WeekItem, type WeekPlan } from "@/lib/api";
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

function Item({ it }: { it: WeekItem }) {
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
        <span className="shrink-0 text-[10px] font-semibold" style={{ color: it.color === "open" || it.color === "skipped" ? "var(--color-muted)" : it.color === "sick" ? "#5b3f8c" : c.bar }}>{status(it)}</span>
      </div>
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

export function WeekDays({ data }: { data: WeekPlan }) {
  return (
    <ol className="grid gap-2" aria-label="Tage der Woche">
      {data.days.map((d) => (
        <li key={d.date} className={`grid gap-2 rounded-lg border bg-surface p-3 sm:grid-cols-[5.5rem_minmax(0,1fr)] ${d.today ? "border-accent ring-1 ring-accent" : "border-line"}`}>
          <div className="flex items-baseline gap-2 sm:block">
            <p className="text-sm font-semibold">{d.weekday} <span className="font-normal text-muted">{dm(d.date)}</span></p>
            {d.today && <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-semibold text-white">heute</span>}
          </div>
          <div className="grid min-w-0 gap-2">
            <DayContext d={d} />
            {d.items.length ? <div className="grid gap-1.5 md:grid-cols-2">{d.items.map((it, i) => <Item key={i} it={it} />)}</div>
              : <p className="text-[11px] text-muted">Ruhetag</p>}
          </div>
        </li>
      ))}
    </ol>
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
