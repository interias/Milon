"use client";

import { useEffect, useRef, useState } from "react";
import type { WeightPoint, WeightZone } from "@/lib/api";
import { de, dm } from "@/lib/format";

// Divergierend: Abnahme blau, stabil grau, Zunahme rot; je kräftiger, desto schneller.
// Grenzen wie weight_phase.ZONES (Cut 0,25/0,5/1 %/Woche, Aufbau 0,25/1/2 %/Monat).
export const ZONES: { key: WeightZone; label: string; color: string }[] = [
  { key: "fast_loss", label: "> 1 %/Woche ab", color: "#0C447C" },
  { key: "cut", label: "Cut 0,5–1 %/Woche", color: "#185FA5" },
  { key: "cut_gentle", label: "Cut schonend 0,25–0,5 %/Woche", color: "#378ADD" },
  { key: "slight_loss", label: "leichte Abnahme", color: "#85B7EB" },
  { key: "stable", label: "stabil ±0,25 %/Monat", color: "#B4B2A9" },
  { key: "bulk_slow", label: "Aufbau 0,25–1 %/Monat", color: "#F09595" },
  { key: "bulk", label: "Aufbau 1–2 %/Monat", color: "#E24B4A" },
  { key: "fast_gain", label: "> 2 %/Monat zu", color: "#A32D2D" },
];
const ZONE = Object.fromEntries(ZONES.map((z) => [z.key, z])) as Record<WeightZone, (typeof ZONES)[number]>;
const HALF = 0.3; // halbe Schlauchbreite in kg, rein optisch
const ts = (date: string) => new Date(`${date}T12:00:00Z`).getTime();
const ok = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);
// Deckend vorgemischt (Farbe über Weiß): halbtransparente Teilstücke würden sich an den Kanten doppeln.
const blend = (hex: string, a: number) => "#" + [1, 3, 5].map((i) => Math.round(parseInt(hex.slice(i, i + 2), 16) * a + 255 * (1 - a)).toString(16).padStart(2, "0")).join("");
const signed = (v: number, d: number) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${de(Math.abs(v), d)}`;

function ticks(lo: number, hi: number) {
  const step = hi - lo > 4 ? 1 : 0.5;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(1));
  return out;
}

export function WeightTube({ points, raw, corridor }: { points: WeightPoint[]; raw: boolean; corridor: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [sel, setSel] = useState<number | null>(null);
  useEffect(() => {
    if (!box.current) return;
    const o = new ResizeObserver(([e]) => setWidth(Math.max(1, e.contentRect.width)));
    o.observe(box.current);
    return () => o.disconnect();
  }, []);
  const pts = [...points].sort((a, b) => ts(a.date) - ts(b.date));
  const vals = pts.flatMap((p) => [
    ...(ok(p.fit) ? [p.fit - HALF, p.fit + HALF] : []),
    ...(ok(p.avg7) ? [p.avg7] : []),
    ...(raw && ok(p.weight) ? [p.weight] : []),
    ...(corridor && ok(p.band_low) && ok(p.band_high) ? [p.band_low, p.band_high] : []),
  ]);
  if (!vals.length) return <div ref={box} className="py-8 text-center text-sm text-muted">Noch zu wenige Wiegungen für den Verlauf.</div>;
  const lo = Math.floor(Math.min(...vals) * 2) / 2, hi = Math.ceil(Math.max(...vals) * 2) / 2;
  const first = ts(pts[0].date), last = ts(pts[pts.length - 1].date);
  const left = 44, right = width - 12, top = 12, bottom = 262;
  const x = (d: string) => first === last ? (left + right) / 2 : left + (ts(d) - first) / (last - first) * (right - left);
  const y = (v: number) => bottom - (v - lo) / (hi - lo || 1) * (bottom - top);
  const active = sel == null ? null : pts[Math.min(sel, pts.length - 1)];
  const pick = (clientX: number, el: SVGSVGElement) => {
    const b = el.getBoundingClientRect();
    const px = (clientX - b.left) / b.width * width;
    const t = first + (px - left) / (right - left) * (last - first);
    let best = 0;
    pts.forEach((p, i) => { if (Math.abs(ts(p.date) - t) < Math.abs(ts(pts[best].date) - t)) best = i; });
    setSel(best);
  };
  const corridorLine = (key: "band_low" | "band_high") => {
    let d = "";
    pts.forEach((p, i) => {
      const v = p[key];
      if (!ok(v)) return;
      d += `${i > 0 && ok(pts[i - 1][key]) && pts[i - 1].phase === p.phase ? "L" : "M"}${x(p.date).toFixed(1)},${y(v).toFixed(1)}`;
    });
    return <path d={d} fill="none" stroke="var(--color-ink)" strokeOpacity="0.55" strokeDasharray="4 4" strokeWidth="1.2" />;
  };
  // 7-Tage-Mittel als Linie; fehlt es (Lücke), bricht die Linie ab.
  let mean = "";
  pts.forEach((p, i) => {
    if (!ok(p.avg7)) return;
    mean += `${i > 0 && ok(pts[i - 1].avg7) ? "L" : "M"}${x(p.date).toFixed(1)},${y(p.avg7).toFixed(1)}`;
  });
  const tickCount = width < 420 ? 3 : 5;
  return <div ref={box} className="relative mt-3 min-w-0 w-full">
    <svg viewBox={`0 0 ${width} 290`} height="290" className="w-full rounded outline-accent" role="group" tabIndex={0}
      aria-label="Gewichtsverlauf als Schlauch, eingefärbt nach der Änderungsrate. Mit den Pfeiltasten einzelne Tage auswählen."
      onPointerMove={(e) => pick(e.clientX, e.currentTarget)}
      onPointerDown={(e) => { e.currentTarget.focus(); pick(e.clientX, e.currentTarget); }}
      onPointerLeave={() => setSel(null)}
      onKeyDown={(e) => {
        if (e.key === "Escape") { setSel(null); return; }
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        setSel((s) => Math.max(0, Math.min(pts.length - 1, s == null ? pts.length - 1 : s + (e.key === "ArrowRight" ? 1 : -1))));
      }}>
      {ticks(lo, hi).map((v) => <g key={v}>
        <line x1={left} x2={right} y1={y(v)} y2={y(v)} stroke="var(--color-line)" />
        <text x={left - 8} y={y(v) + 4} textAnchor="end" fontSize="12" fill="var(--color-muted)">{de(v, v % 1 ? 1 : 0)}</text>
      </g>)}
      {pts.map((p, i) => {
        const q = pts[i - 1];
        if (!q || !ok(p.fit) || !ok(q.fit) || !p.zone) return null;
        const c = blend(ZONE[p.zone].color, p.sure ? 0.9 : 0.32);
        return <polygon key={p.date} points={`${x(q.date)},${y(q.fit + HALF)} ${x(p.date)},${y(p.fit + HALF)} ${x(p.date)},${y(p.fit - HALF)} ${x(q.date)},${y(q.fit - HALF)}`}
          fill={c} stroke={c} strokeWidth="0.8" strokeLinejoin="round" />;
      })}
      <path d={mean} fill="none" stroke="var(--color-ink)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      {corridor && <>{corridorLine("band_low")}{corridorLine("band_high")}</>}
      {raw && pts.map((p) => ok(p.weight) && <circle key={`r${p.date}`} cx={x(p.date)} cy={y(p.weight)} r="2" fill="var(--color-ink)" fillOpacity="0.45" />)}
      {active && <line x1={x(active.date)} x2={x(active.date)} y1={top} y2={bottom} stroke="var(--color-muted)" strokeDasharray="3 3" />}
      {active && ok(active.avg7) && <circle cx={x(active.date)} cy={y(active.avg7)} r="4" fill="var(--color-surface)" stroke="var(--color-ink)" strokeWidth="1.5" />}
      {Array.from({ length: tickCount }, (_, i) => {
        const f = i / (tickCount - 1);
        return <text key={i} x={left + f * (right - left)} y="284" textAnchor={i === 0 ? "start" : i === tickCount - 1 ? "end" : "middle"} fontSize="12" fill="var(--color-muted)">{dm(new Date(first + f * (last - first)).toISOString())}</text>;
      })}
    </svg>
    {active && <div className="pointer-events-none absolute right-2 top-0 max-w-[calc(100%-3.5rem)] rounded border border-line bg-surface/95 px-3 py-2 text-xs shadow-sm" role="status" aria-live="polite">
      <p className="font-semibold">{dm(active.date)}{active.date.slice(0, 4)}{ok(active.avg7) ? ` · 7-Tage-Mittel ${de(active.avg7, 1)} kg` : ""}</p>
      {ok(active.weight) && <p className="mt-0.5 text-muted">gewogen {de(active.weight, 1)} kg</p>}
      {active.zone && ok(active.rate_pct) && ok(active.fit) ? <>
        <p className="mt-0.5"><span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm align-middle" style={{ background: ZONE[active.zone].color }} />{ZONE[active.zone].label}</p>
        <p className="mt-0.5 text-muted">{signed(active.rate_pct / 100 * active.fit, 2)} kg/Woche · {signed(active.rate_pct, 2)} %/Woche</p>
        <p className="mt-0.5 text-muted">Spanne {signed(active.rate_pct - (active.rate_ci ?? 0), 2)} bis {signed(active.rate_pct + (active.rate_ci ?? 0), 2)} %/Woche{active.sure ? "" : " · noch unsicher"}{active.edge ? " · Rand (Daten nur auf einer Seite)" : ""}</p>
      </> : <p className="mt-0.5 text-muted">Zu wenige Wiegungen ±14 Tage</p>}
      {corridor && active.phase && ok(active.band_low) && <p className="mt-0.5 text-muted">Zielkorridor {active.phase}: {de(active.band_low, 1)}–{de(active.band_high, 1)} kg</p>}
    </div>}
    <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted" aria-label="Legende Änderungsrate">
      <li className="flex items-center gap-1"><span className="inline-block h-0.5 w-3.5 rounded bg-ink" />7-Tage-Mittel</li>
      {ZONES.map((z) => <li key={z.key} className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: z.color }} />{z.label}</li>)}
    </ul>
  </div>;
}
