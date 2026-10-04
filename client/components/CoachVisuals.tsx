"use client";

import { Bars } from "@/components/charts";
import { RunTrendChart } from "@/components/RunTrendChart";
import type { CoachVisual } from "@/lib/api";

const dateLabel = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });

export function CoachVisuals({ visuals, compact = false }: { visuals: CoachVisual[]; compact?: boolean }) {
  if (!visuals.length) return null;
  return <div className={`grid gap-4 ${compact ? "lg:grid-cols-3" : "md:grid-cols-2"}`}>
    {visuals.map((visual) => {
      const measured = visual.points.filter((point) => point.value != null);
      const last = measured.at(-1);
      return <section key={visual.id} aria-label={visual.title} className="min-w-0 rounded-card border border-line bg-surface-alt p-4">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
          <h3 className="text-sm font-semibold">{visual.title}</h3>
          {last && <p className="font-display text-xl font-semibold tabular-nums">{last.value!.toLocaleString("de-DE", { maximumFractionDigits: 1 })}<span className="ml-1 text-xs font-normal text-muted">{visual.unit}</span></p>}
        </div>
        {visual.kind === "bars" ? <Bars height={compact ? 140 : 200} unit={visual.unit}
          data={measured.map((point) => ({ label: dateLabel(point.date), value: point.value! }))} />
          : <RunTrendChart label={visual.title} unit={visual.unit} showPoints={false}
            points={visual.points} />}
        <p className="mt-3 text-xs leading-relaxed text-muted">{visual.description}</p>
        {visual.points.length > 0 && <p className="mt-2 text-[11px] text-muted">{dateLabel(visual.points[0].date)}–{dateLabel(visual.points.at(-1)!.date)} · {measured.length} Werte</p>}
      </section>;
    })}
  </div>;
}
