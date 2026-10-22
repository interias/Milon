"use client";

import { useEffect, useState } from "react";
import { api, type WeeklyVolume as Data } from "@/lib/api";
import { Card } from "@/components/ui";
import { de, dm } from "@/lib/format";

// Harte Sätze je Muskel und Woche: Balken = diese Woche, Strich = Ø der 4 Wochen davor,
// Raute = Soll laut Plan, Band = belegter Bereich 10–20.
export function WeeklyVolume() {
  const [data, setData] = useState<Data | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    api.strengthVolume().then((value) => { if (active) setData(value); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);

  if (!data) return <Card><h2 className="text-sm font-semibold">Wochenvolumen</h2><p className="mt-2 text-sm text-muted" role="status">{failed ? "Daten konnten nicht geladen werden." : "Wird geladen …"}</p></Card>;
  const [lo, hi] = data.band;
  const max = Math.max(hi + 4, ...data.muscles.flatMap((m) => [m.this_week, m.avg_4w, m.planned]));
  const pct = (value: number) => `${(Math.min(value, max) / max) * 100}%`;

  return <Card>
    <h2 className="text-sm font-semibold">Wochenvolumen</h2>
    <p className="mt-1 text-xs text-muted">Harte Sätze je Muskel (≤ 3 Wdh. Reserve), Woche ab {dm(data.week_start)} · mitbeteiligte Muskeln zählen halb</p>
    <div className="mt-3 space-y-2">
      {data.muscles.map((m) => <div key={m.muscle} className="grid grid-cols-[7.5rem_1fr] items-center gap-2 sm:grid-cols-[9rem_1fr_9rem] sm:gap-3">
        <span className="truncate text-xs">{m.muscle}</span>
        <div className="relative h-4 rounded bg-surface-alt" role="img" aria-label={`${m.muscle}: diese Woche ${de(m.this_week, 1)}, Durchschnitt ${de(m.avg_4w, 1)}, Plan ${de(m.planned, 1)}`}>
          <div className="absolute inset-y-0 bg-accent-2/25" style={{ left: pct(lo), width: `calc(${pct(hi)} - ${pct(lo)})` }} />
          <div className="absolute inset-y-1 left-0 rounded-sm bg-accent" style={{ width: pct(m.this_week) }} />
          <div className="absolute -inset-y-0.5 w-0.5 bg-ink" style={{ left: pct(m.avg_4w) }} title={`Ø 4 Wochen: ${de(m.avg_4w, 1)}`} />
          <div className="absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rotate-45 border border-ink bg-surface" style={{ left: pct(m.planned) }} title={`Plan: ${de(m.planned, 1)}`} />
        </div>
        <span className="col-start-2 text-[11px] tabular-nums text-muted sm:col-start-3 sm:text-xs">{de(m.this_week, 1)} · Ø {de(m.avg_4w, 1)} · Plan {de(m.planned, 1)}</span>
      </div>)}
    </div>
    <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
      <span><span className="mr-1 inline-block h-2 w-3 rounded-sm bg-accent align-middle" />diese Woche</span>
      <span><span className="mr-1 inline-block h-3 w-0.5 bg-ink align-middle" />Ø 4 Wochen davor</span>
      <span><span className="mr-1 inline-block h-2 w-2 rotate-45 border border-ink align-middle" />Plan</span>
      <span><span className="mr-1 inline-block h-2 w-3 bg-accent-2/25 align-middle" />Bereich {lo}–{hi}</span>
    </p>
  </Card>;
}
