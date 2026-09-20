"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { de, dm } from "@/lib/format";

type TrendPoint = {
  date: string;
  value: number | null;
  low?: number | null;
  high?: number | null;
  segment_id?: string | number;
  status?: string;
  detail?: string;
};
type Observation = { date: string; value: number | null; detail?: string };
const timestamp = (date: string) => new Date(`${date.slice(0, 10)}T12:00:00Z`).getTime();
const finite = (value: number | null | undefined): value is number => value != null && Number.isFinite(value);
const connected = (a: TrendPoint | undefined, b: TrendPoint | undefined) => !!a && !!b
  && finite(a.value) && finite(b.value) && a.segment_id === b.segment_id
  && timestamp(b.date) - timestamp(a.date) <= 56 * 86400000;
const hasInterval = (point: TrendPoint) => finite(point.low) && finite(point.high);

function axis(values: number[]) {
  const min = Math.min(...values), max = Math.max(...values);
  const padding = Math.max((max - min) * 0.06, 0.5);
  const lower = min - padding, upper = max + padding;
  const base = 10 ** Math.floor(Math.log10((upper - lower) / 6));
  const candidates = [0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 10].map((factor) => {
    const step = base * factor;
    const low = Math.floor(lower / step) * step, high = Math.ceil(upper / step) * step;
    const count = Math.round((high - low) / step) + 1;
    return { step, low, high, count };
  });
  const best = candidates.sort((a, b) => Math.abs(a.count - 7) - Math.abs(b.count - 7))[0];
  return { ...best, ticks: Array.from({ length: best.count }, (_, i) => best.low + i * best.step) };
}

export function RunTrendChart({ points, unit, label, observations = [], showPoints = true }: {
  points: TrendPoint[];
  unit: string;
  label: string;
  observations?: Observation[];
  showPoints?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(280);
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => {
    if (!container.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(1, entry.contentRect.width)));
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  const sorted = [...points].sort((a, b) => timestamp(a.date) - timestamp(b.date));
  const selectable = [...sorted, ...observations].filter((p) => finite(p.value))
    .sort((a, b) => timestamp(a.date) - timestamp(b.date));
  const values = [...sorted.flatMap((p) => finite(p.value) ? [p.value, p.low, p.high] : []), ...observations.map((p) => p.value)].filter(finite);
  if (!values.length) return <div ref={container} className="py-8 text-center text-sm text-muted">Noch keine geeigneten Werte für diese Darstellung.</div>;
  const scale = axis(values);
  const dates = [...sorted, ...observations].map((p) => timestamp(p.date));
  const first = Math.min(...dates), last = Math.max(...dates);
  const left = 48, right = width - 15, top = 18, bottom = 264;
  const x = (date: string) => first === last ? (left + right) / 2 : left + (timestamp(date) - first) / (last - first) * (right - left);
  const y = (value: number) => bottom - (value - scale.low) / (scale.high - scale.low) * (bottom - top);
  const active: TrendPoint | undefined = selected == null ? undefined : selectable[Math.min(selected, selectable.length - 1)];
  const tickCount = first === last ? 1 : width < 420 ? 3 : 5;
  const decimals = [0, 1, 2, 3].find((digits) => Math.abs(scale.step * 10 ** digits - Math.round(scale.step * 10 ** digits)) < 1e-8) ?? 3;
  function selectPoint(event: PointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const px = (event.clientX - bounds.left) / bounds.width * width;
    const py = (event.clientY - bounds.top) / bounds.height * 300;
    let nearest = 0, distance = Infinity;
    selectable.forEach((point, index) => {
      const next = Math.hypot(x(point.date) - px, y(point.value!) - py);
      if (next < distance) { nearest = index; distance = next; }
    });
    setSelected(nearest);
  }
  return <div ref={container} className="relative mt-3 min-w-0 w-full">
    <svg viewBox={`0 0 ${width} 300`} height="300" className="w-full rounded outline-accent" role="group" tabIndex={0}
      aria-label={`${label}. ${unit}. Mit den Pfeiltasten einzelne Werte auswählen.`}
      onKeyDown={(event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
        event.preventDefault();
        if (event.key === "Escape") { setSelected(null); return; }
        if (event.key === "Home") { setSelected(0); return; }
        if (event.key === "End") { setSelected(selectable.length - 1); return; }
        setSelected((previous) => Math.max(0, Math.min(selectable.length - 1,
          previous == null ? (event.key === "ArrowRight" ? 0 : selectable.length - 1) : previous + (event.key === "ArrowRight" ? 1 : -1))));
      }}
      onPointerMove={selectPoint}
      onPointerDown={(event) => { event.currentTarget.focus(); selectPoint(event); }}>
      {scale.ticks.map((value) => <g key={value}>
        <line x1={left} x2={right} y1={y(value)} y2={y(value)} stroke="var(--color-line)" />
        <text x={left - 9} y={y(value) + 5} textAnchor="end" fontSize="14" fill="var(--color-muted)">{de(value, decimals)}</text>
      </g>)}
      {sorted.map((point, index) => {
        if (!finite(point.value) || !hasInterval(point)) return null;
        const previous = sorted[index - 1], next = sorted[index + 1];
        const before = connected(previous, point) && hasInterval(previous);
        const after = connected(point, next) && hasInterval(next);
        if (before) return <polygon key={`band-${index}`} points={`${x(previous.date)},${y(previous.low!)} ${x(point.date)},${y(point.low!)} ${x(point.date)},${y(point.high!)} ${x(previous.date)},${y(previous.high!)}`} fill="var(--color-accent)" opacity="0.1" />;
        if (!after) return <line key={`interval-${index}`} x1={x(point.date)} x2={x(point.date)} y1={y(point.low!)} y2={y(point.high!)} stroke="var(--color-accent)" opacity="0.2" />;
        return null;
      })}
      {observations.filter((p) => finite(p.value)).map((point, index) => <circle key={`raw-${index}`} cx={x(point.date)} cy={y(point.value!)} r="3" fill="var(--color-accent-2)" opacity="0.55" />)}
      {sorted.map((point, index) => {
        if (!finite(point.value)) return null;
        const previous = sorted[index - 1];
        return <g key={`point-${index}`}>
          {connected(previous, point) && <line x1={x(previous.date)} y1={y(previous.value!)} x2={x(point.date)} y2={y(point.value)} stroke="var(--color-accent)" strokeWidth="2" />}
          {(showPoints || (!connected(previous, point) && !connected(point, sorted[index + 1]))) && <circle cx={x(point.date)} cy={y(point.value)} r="3" fill={point.status === "sensitive" ? "var(--color-surface)" : "var(--color-accent)"} stroke="var(--color-accent)" strokeWidth="1.5" />}
        </g>;
      })}
      {active && <circle cx={x(active.date)} cy={y(active.value!)} r="5" fill="var(--color-surface)" stroke="var(--color-accent)" strokeWidth="2" />}
      {Array.from({ length: tickCount }, (_, i) => {
        const fraction = tickCount === 1 ? 0.5 : i / (tickCount - 1);
        return <text key={i} x={left + fraction * (right - left)} y="290" textAnchor={tickCount === 1 ? "middle" : i === 0 ? "start" : i === tickCount - 1 ? "end" : "middle"} fontSize="13" fill="var(--color-muted)">{dm(new Date(first + fraction * (last - first)).toISOString())}</text>;
      })}
    </svg>
    {active && <div className="pointer-events-none absolute right-2 top-0 max-w-[calc(100%-3.5rem)] rounded border border-line bg-surface/95 px-3 py-2 text-xs shadow-sm" role="status" aria-live="polite">
      <p className="font-semibold">{dm(active.date)}{active.date.slice(0, 4)} · {de(active.value, 1)} {unit}</p>
      {hasInterval(active) && <p className="mt-0.5 text-muted">95%-Intervall: {de(active.low, 1)}–{de(active.high, 1)} {unit}</p>}
      {active.detail && <p className="mt-0.5 text-muted">{active.detail}</p>}
      {active.status === "sensitive" && <p className="mt-0.5 text-muted">Empfindlich gegenüber einzelnen Läufen</p>}
    </div>}
  </div>;
}
