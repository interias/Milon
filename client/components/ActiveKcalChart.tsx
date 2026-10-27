"use client";

import { useEffect, useState } from "react";
import { api, type ActiveKcal, type ActiveKcalDay } from "@/lib/api";
import { Card } from "@/components/ui";
import { de0, dm } from "@/lib/format";

// Feste Reihenfolge, per dataviz-Validator geprüft (light: CVD-ΔE ≥ 10,3, Kontrast ≥ 3:1).
const PARTS = [
  { key: "everyday", label: "Alltag", color: "#00917d" },
  { key: "run", label: "Laufen", color: "#2a78d6" },
  { key: "ride", label: "Rad", color: "#ab7f00" },
  { key: "walkpad", label: "Laufband", color: "#b53415" },
  { key: "gym", label: "Gym", color: "#d4579a" },
] as const;

const iso = (d: Date) => d.toLocaleDateString("sv-SE");

// Lückenlose Tagesachse: Tage ohne Daten bleiben leer statt zu verschwinden.
function fillDays(series: ActiveKcalDay[], days: number): (ActiveKcalDay | { date: string; total: null })[] {
  const byDate = new Map(series.map((d) => [d.date, d]));
  const last = series.at(-1)?.date ?? iso(new Date());
  const end = new Date(`${last}T12:00:00`);
  return Array.from({ length: days }, (_, i) => {
    const d = new Date(end);
    d.setDate(end.getDate() - (days - 1 - i));
    return byDate.get(iso(d)) ?? { date: iso(d), total: null };
  });
}

export function ActiveKcalChart({ days = 30, height = 190, revision = 0 }: { days?: number; height?: number; revision?: number }) {
  const [data, setData] = useState<ActiveKcal | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    api.activeKcal(days).then((v) => { if (active) setData(v); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [days, revision]);

  const full = data?.series.filter((d) => !d.provisional) ?? [];
  const avg = full.length ? full.reduce((a, d) => a + d.total, 0) / full.length : null;
  const bars = data ? fillDays(data.series, days) : [];
  const max = Math.max(...bars.map((d) => d.total ?? 0), 1);
  const stride = Math.max(1, Math.ceil(days / 7));
  const labelH = 18, plotH = height - labelH - 4;
  const used = PARTS.filter((p) => data?.series.some((d) => d[p.key] > 0));

  return <Card className="mt-4">
    <h2 className="text-sm font-semibold">Aktive Kalorien · letzte {days} Tage</h2>
    {!data ? <p className="mt-3 text-xs text-muted" role="status">{failed ? "Daten konnten nicht geladen werden." : "Wird geladen …"}</p> : <>
      <p className="mt-3 font-display text-3xl font-extrabold">{avg != null ? de0(avg) : "–"} <span className="text-sm font-normal text-muted">kcal/Tag im Schnitt</span></p>
      <p className="mt-1 text-xs text-muted">{full.length} volle Tage{data.today ? ` · heute bisher ${de0(data.today.total)} kcal` : ""} · Ø 7 Tage {data.avg7 != null ? `${de0(data.avg7)} kcal` : "–"}</p>
      <div className="mt-4 flex" style={{ height }}>
        <div className="flex w-10 shrink-0 flex-col justify-between pr-2 text-right text-[10px] leading-none text-muted sm:w-14" style={{ paddingBottom: labelH + 4 }}>
          {[max, max / 2, 0].map((t, k) => <span key={k}>{de0(t)}</span>)}
        </div>
        <div className="flex min-w-0 flex-1 items-end gap-[2px]">
          {bars.map((d, i) => {
            const day = d.total != null ? d as ActiveKcalDay : null;
            const tip = day ? `${dm(d.date)}${day.provisional ? " (heute bisher)" : ""}: ${de0(day.total)} kcal\n` +
              PARTS.filter((p) => day[p.key] > 0).map((p) => `${p.label} ${de0(day[p.key])}`).join(" · ") +
              (day.garmin != null ? `\nGarmin: ${de0(day.garmin)} kcal` : "") : `${dm(d.date)}: keine Daten`;
            return <div key={d.date} title={tip} className="group flex h-full min-w-0 flex-1 flex-col items-center justify-end">
              <div className="flex w-full flex-col-reverse overflow-hidden rounded-t group-hover:brightness-110"
                style={{ height: day ? Math.max(day.total > 0 ? 2 : 0, (day.total / max) * plotH) : 0, opacity: day?.provisional ? 0.5 : 1 }}>
                {day && PARTS.map((p) => day[p.key] > 0 && <div key={p.key}
                  style={{ height: `${(day[p.key] / day.total) * 100}%`, background: p.color, borderTop: "2px solid var(--color-surface)" }} />)}
              </div>
              <span className="mt-1 w-full whitespace-nowrap text-center text-[9px] leading-none text-muted" style={{ height: labelH }}>
                {(i % stride === 0 && i < bars.length - stride) || i === bars.length - 1 ? dm(d.date) : ""}
              </span>
            </div>;
          })}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {used.map((p) => <span key={p.key} className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: p.color }} />{p.label}</span>)}
        {data.today && <span>heller Balken = heute, noch unvollständig</span>}
      </div>
      <details className="mt-3 text-xs text-muted">
        <summary className="cursor-pointer py-1">Werte als Tabelle (kcal)</summary>
        <div className="overflow-x-auto">
          <table className="mt-2 w-full tabular-nums">
            <thead><tr className="border-b border-line text-right"><th className="pb-1 text-left font-medium">Tag</th>
              {PARTS.map((p) => <th key={p.key} className="pb-1 font-medium">{p.label}</th>)}
              <th className="pb-1 font-medium">Summe</th><th className="pb-1 font-medium">Garmin</th></tr></thead>
            <tbody className="divide-y divide-line">
              {[...data.series].reverse().map((d) => <tr key={d.date} className="text-right">
                <th scope="row" className="py-1 text-left font-medium text-ink">{dm(d.date)}</th>
                {PARTS.map((p) => <td key={p.key} className="py-1">{d[p.key] ? de0(d[p.key]) : "–"}</td>)}
                <td className="py-1 font-semibold text-ink">{de0(d.total)}</td><td className="py-1">{d.garmin != null ? de0(d.garmin) : "–"}</td>
              </tr>)}
            </tbody>
          </table>
        </div>
      </details>
      <p className="mt-3 text-xs text-muted">Von Milon aus deinen Daten berechnet, nur Kalorien über dem Ruheumsatz · Garmins eigene Schätzung steht zum Vergleich im Tooltip und in der Tabelle.</p>
    </>}
  </Card>;
}
