// Leichte Inline-SVG-Charts mit Achsen (keine Chart-Lib -> keine React-19-Peer-Konflikte).
// Y-Achse: Werteskala (auto). X-Achse: Zeit-/Kategorie-Labels (HTML, gestochen scharf).
import React from "react";
import { de, dm } from "@/lib/format";

type Fmt = (n: number) => string;

function domain(ys: number[]): [number, number] {
  const min = Math.min(...ys), max = Math.max(...ys);
  if (min === max) return [min - 1, max + 1];
  const pad = (max - min) * 0.1;
  return [min - pad, max + pad];
}

function pickTicks(labels: string[] | undefined, n: number, want = 5): { i: number; label: string }[] {
  if (!labels || labels.length === 0) return [];
  const k = Math.min(want, labels.length);
  const out: { i: number; label: string }[] = [];
  for (let j = 0; j < k; j++) {
    const i = Math.round((j / Math.max(1, k - 1)) * (labels.length - 1));
    if (!out.length || out[out.length - 1].i !== i) out.push({ i, label: labels[i] });
  }
  return out;
}

export function AreaTrend({
  values,
  labels,
  height = 180,
  unit,
  format = (n) => de(n, 1),
  className = "text-accent",
}: {
  values: (number | null)[];
  labels?: string[];
  height?: number;
  unit?: string;
  format?: Fmt;
  className?: string;
}) {
  const pts0 = values
    .map((v, i) => ({ i, v }))
    .filter((p): p is { i: number; v: number } => p.v != null);
  if (pts0.length < 2) {
    return <div style={{ height }} className="grid place-items-center text-xs text-muted">keine Daten</div>;
  }
  const [lo, hi] = domain(pts0.map((p) => p.v));
  const range = hi - lo || 1;
  const W = 100, H = 100, n = values.length;
  const X = (i: number) => (n <= 1 ? 0 : (i / (n - 1)) * W);
  const Y = (v: number) => H - ((v - lo) / range) * H;
  const pts = pts0.map((p) => [X(p.i), Y(p.v)] as const);
  const line = pts.map((p, k) => (k ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2)).join(" ");
  const last = pts[pts.length - 1];
  const area = `${line} L${last[0].toFixed(2)} ${H} L${pts[0][0].toFixed(2)} ${H} Z`;
  const yticks = [hi, (hi + lo) / 2, lo];
  const xticks = pickTicks(labels, n);
  const u = unit ? ` ${unit}` : "";

  return (
    <div className={className}>
      <div className="flex" style={{ height }}>
        <div className="flex w-10 shrink-0 flex-col justify-between pr-2 text-right text-[10px] leading-none text-muted sm:w-14">
          {yticks.map((t, k) => <span key={k}>{format(t)}{u}</span>)}
        </div>
        <div className="min-w-0 flex-1">
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: "100%" }}>
            {[0, 0.5, 1].map((g) => (
              <line key={g} x1="0" x2={W} y1={g * H} y2={g * H} stroke="var(--color-line)" strokeWidth="0.5" vectorEffect="non-scaling-stroke" />
            ))}
            <path d={area} fill="currentColor" fillOpacity={0.12} />
            <path d={line} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          </svg>
        </div>
      </div>
      {xticks.length > 0 && (
        <div className="ml-10 mt-1 flex justify-between text-[10px] text-muted sm:ml-14">
          {xticks.map((t, k) => <span key={k}>{t.label}</span>)}
        </div>
      )}
    </div>
  );
}

export function Sparkline({ values, height = 40, className = "text-accent" }: { values: (number | null)[]; height?: number; className?: string }) {
  const data = values.filter((v): v is number => v != null);
  if (data.length < 2) return <div style={{ height }} />;
  const W = 100, H = 32, pad = 2;
  const min = Math.min(...data), max = Math.max(...data), range = max - min || 1;
  const pts = data.map((v, i) => [pad + (i / (data.length - 1)) * (W - 2 * pad), pad + (1 - (v - min) / range) * (H - 2 * pad)] as const);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2)).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height }} className={className}>
      <path d={line} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function Bars({
  data,
  height = 180,
  unit,
  className = "text-accent",
}: {
  data: { label: string; value: number }[];
  height?: number;
  unit?: string;
  className?: string;
}) {
  if (!data.length) return <div style={{ height }} className="grid place-items-center text-xs text-muted">keine Daten</div>;
  const max = Math.max(...data.map((d) => d.value), 1);
  const xLabelH = 18;
  const plotH = height - xLabelH;
  const yticks = [max, max / 2, 0];
  const stride = Math.max(1, Math.ceil(data.length / 7));
  const u = unit ? ` ${unit}` : "";

  return (
    <div className={className}>
      <div className="flex" style={{ height }}>
        <div className="flex w-10 shrink-0 flex-col justify-between pr-2 text-right text-[10px] leading-none text-muted sm:w-14" style={{ paddingBottom: xLabelH }}>
          {yticks.map((t, k) => <span key={k}>{de(t, 0)}{u}</span>)}
        </div>
        <div className="flex min-w-0 flex-1 items-end gap-1.5">
          {data.map((d, i) => (
            <div key={i} className="flex flex-1 flex-col items-center justify-end" style={{ height }} title={`${d.label}: ${d.value}${u}`}>
              <div className="w-full rounded-t bg-current" style={{ height: Math.max(2, (d.value / max) * plotH), opacity: 0.85 }} />
              <span className="mt-1 w-full truncate text-center text-[9px] leading-none text-muted" style={{ height: xLabelH }}>
                {i % stride === 0 || i === data.length - 1 ? d.label : ""}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Trend-Chart mit linearer 30-Tage-Prognose: durchgezogene History + gestrichelte
// Extrapolation + horizontale Linie auf dem projizierten Endwert (Zeitachse datumsbasiert,
// damit History- und Prognose-Abschnitt korrekt skaliert nebeneinander liegen).
export function ForecastChart({
  history,
  forecast,
  projected,
  height = 210,
  unit,
  format = (n) => de(n, 1),
}: {
  history: { date: string; value: number }[];
  forecast: { date: string; value: number }[];
  projected: number | null;
  height?: number;
  unit?: string;
  format?: Fmt;
}) {
  if (history.length < 2 || forecast.length < 2 || projected == null) {
    return <div style={{ height }} className="grid place-items-center text-xs text-muted">keine Prognose</div>;
  }
  const all = [...history, ...forecast];
  const [lo, hi] = domain([...all.map((p) => p.value), projected]);
  const range = hi - lo || 1;
  const ts = all.map((p) => +new Date(p.date));
  const tMin = Math.min(...ts), tMax = Math.max(...ts), tRange = tMax - tMin || 1;
  const W = 100, H = 100;
  const X = (d: string) => ((+new Date(d) - tMin) / tRange) * W;
  const Y = (v: number) => H - ((v - lo) / range) * H;
  const pathOf = (pts: { date: string; value: number }[]) =>
    pts.map((p, k) => (k ? "L" : "M") + X(p.date).toFixed(2) + " " + Y(p.value).toFixed(2)).join(" ");
  const todayX = X(forecast[0].date);
  const projY = Y(projected);
  const yticks = [hi, (hi + lo) / 2, lo];
  const u = unit ? ` ${unit}` : "";

  return (
    <div className="text-accent">
      <div className="flex" style={{ height }}>
        <div className="flex w-10 shrink-0 flex-col justify-between pr-2 text-right text-[10px] leading-none text-muted sm:w-14">
          {yticks.map((t, k) => <span key={k}>{format(t)}{u}</span>)}
        </div>
        <div className="relative min-w-0 flex-1">
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: "100%" }}>
            {[0, 0.5, 1].map((g) => (
              <line key={g} x1="0" x2={W} y1={g * H} y2={g * H} stroke="var(--color-line)" strokeWidth="0.5" vectorEffect="non-scaling-stroke" />
            ))}
            {/* heute-Trennlinie (History | Prognose) */}
            <line x1={todayX} x2={todayX} y1="0" y2={H} stroke="var(--color-line)" strokeWidth="1" strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
            {/* Horizontale Linie auf dem extrapolierten Wert */}
            <line x1="0" x2={W} y1={projY} y2={projY} stroke="var(--color-accent-2)" strokeWidth="1.2" strokeDasharray="3 2" vectorEffect="non-scaling-stroke" />
            {/* History durchgezogen */}
            <path d={pathOf(history)} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            {/* Prognose gestrichelt */}
            <path d={pathOf(forecast)} fill="none" stroke="currentColor" strokeOpacity="0.85" strokeWidth="2" strokeDasharray="4 3" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          </svg>
          {/* Wert-Label auf der Horizontallinie */}
          <span
            className="pointer-events-none absolute right-0 -translate-y-1/2 rounded bg-surface/90 px-1 text-[10px] font-bold"
            style={{ top: `${Math.max(5, Math.min(95, projY))}%`, color: "var(--color-accent-2)" }}
          >
            {format(projected)}{u}
          </span>
        </div>
      </div>
      <div className="relative ml-10 mt-1 h-3 text-[10px] text-muted sm:ml-14">
        <span className="absolute left-0">{dm(history[0].date)}</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${todayX}%` }}>heute</span>
        <span className="absolute right-0">{dm(forecast[forecast.length - 1].date)}</span>
      </div>
    </div>
  );
}

export function MultiTrend({
  series,
  labels,
  height = 200,
  unit,
  format = (n) => de(n, 1),
}: {
  series: { values: (number | null)[]; label: string; color: string }[];
  labels?: string[];
  height?: number;
  unit?: string;
  format?: Fmt;
}) {
  const allY = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  if (allY.length < 2) {
    return <div style={{ height }} className="grid place-items-center text-xs text-muted">keine Daten</div>;
  }
  const [lo, hi] = domain(allY);
  const range = hi - lo || 1;
  const W = 100, H = 100;
  const n = Math.max(...series.map((s) => s.values.length), 1);
  const X = (i: number) => (n <= 1 ? 0 : (i / (n - 1)) * W);
  const Y = (v: number) => H - ((v - lo) / range) * H;
  const path = (vals: (number | null)[]) => {
    const pts = vals.map((v, i) => ({ i, v })).filter((p): p is { i: number; v: number } => p.v != null);
    if (pts.length < 2) return "";
    return pts.map((p, k) => (k ? "L" : "M") + X(p.i).toFixed(2) + " " + Y(p.v).toFixed(2)).join(" ");
  };
  const yticks = [hi, (hi + lo) / 2, lo];
  const xticks = pickTicks(labels, n);
  const u = unit ? ` ${unit}` : "";

  return (
    <div>
      <div className="flex" style={{ height }}>
        <div className="flex w-10 shrink-0 flex-col justify-between pr-2 text-right text-[10px] leading-none text-muted sm:w-14">
          {yticks.map((t, k) => <span key={k}>{format(t)}{u}</span>)}
        </div>
        <div className="min-w-0 flex-1">
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: "100%" }}>
            {[0, 0.5, 1].map((g) => (
              <line key={g} x1="0" x2={W} y1={g * H} y2={g * H} stroke="var(--color-line)" strokeWidth="0.5" vectorEffect="non-scaling-stroke" />
            ))}
            {series.map((s, si) => (
              <path key={si} d={path(s.values)} fill="none" stroke={s.color}
                    strokeWidth={si === series.length - 1 ? 2.2 : 1.3}
                    strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            ))}
          </svg>
        </div>
      </div>
      {xticks.length > 0 && (
        <div className="ml-10 mt-1 flex justify-between text-[10px] text-muted sm:ml-14">
          {xticks.map((t, k) => <span key={k}>{t.label}</span>)}
        </div>
      )}
      <div className="ml-10 mt-1.5 flex flex-wrap gap-3 sm:ml-14">
        {series.map((s, i) => (
          <span key={i} className="flex items-center gap-1 text-[10px] text-muted">
            <span className="inline-block h-[2px] w-3.5" style={{ background: s.color }} />{s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

// Zwei Linien mit EIGENER Y-Skala (links/rechts) auf gemeinsamer X-Achse. Für Overlays wie
// Stärke-Index (links) vs. Defizit (rechts), wo die Einheiten völlig verschieden sind.
export function DualAxisTrend({
  labels,
  left,
  right,
  height = 210,
}: {
  labels?: string[];
  left: { values: (number | null)[]; label: string; color: string; format?: Fmt };
  right: { values: (number | null)[]; label: string; color: string; format?: Fmt };
  height?: number;
}) {
  const lf = left.format ?? ((n) => de(n, 0));
  const rf = right.format ?? ((n) => de(n, 0));
  const lv = left.values.filter((v): v is number => v != null);
  const rv = right.values.filter((v): v is number => v != null);
  if (lv.length < 2 || rv.length < 2) {
    return <div style={{ height }} className="grid place-items-center text-xs text-muted">keine Daten</div>;
  }
  const [llo, lhi] = domain(lv);
  const [rlo, rhi] = domain(rv);
  const W = 100, H = 100;
  const n = Math.max(left.values.length, right.values.length, 1);
  const X = (i: number) => (n <= 1 ? 0 : (i / (n - 1)) * W);
  const YL = (v: number) => H - ((v - llo) / (lhi - llo || 1)) * H;
  const YR = (v: number) => H - ((v - rlo) / (rhi - rlo || 1)) * H;
  const path = (vals: (number | null)[], Y: (v: number) => number) => {
    const pts = vals.map((v, i) => ({ i, v })).filter((p): p is { i: number; v: number } => p.v != null);
    if (pts.length < 2) return "";
    return pts.map((p, k) => (k ? "L" : "M") + X(p.i).toFixed(2) + " " + Y(p.v).toFixed(2)).join(" ");
  };
  const lticks = [lhi, (lhi + llo) / 2, llo];
  const rticks = [rhi, (rhi + rlo) / 2, rlo];
  const xticks = pickTicks(labels, n);
  const showZero = rlo < 0 && rhi > 0;

  return (
    <div>
      <div className="flex" style={{ height }}>
        <div className="flex w-9 shrink-0 flex-col justify-between pr-1.5 text-right text-[10px] leading-none sm:w-12" style={{ color: left.color }}>
          {lticks.map((t, k) => <span key={k}>{lf(t)}</span>)}
        </div>
        <div className="min-w-0 flex-1">
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: "100%" }}>
            {[0, 0.5, 1].map((g) => (
              <line key={g} x1="0" x2={W} y1={g * H} y2={g * H} stroke="var(--color-line)" strokeWidth="0.5" vectorEffect="non-scaling-stroke" />
            ))}
            {showZero && (
              <line x1="0" x2={W} y1={YR(0)} y2={YR(0)} stroke={right.color} strokeWidth="0.7" strokeDasharray="2 2" opacity="0.55" vectorEffect="non-scaling-stroke" />
            )}
            <path d={path(right.values, YR)} fill="none" stroke={right.color} strokeWidth="1.5" strokeDasharray="3 2.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
            <path d={path(left.values, YL)} fill="none" stroke={left.color} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          </svg>
        </div>
        <div className="flex w-11 shrink-0 flex-col justify-between pl-1.5 text-left text-[10px] leading-none sm:w-14" style={{ color: right.color }}>
          {rticks.map((t, k) => <span key={k}>{rf(t)}</span>)}
        </div>
      </div>
      {xticks.length > 0 && (
        <div className="ml-9 mr-11 mt-1 flex justify-between text-[10px] text-muted sm:ml-12 sm:mr-14">
          {xticks.map((t, k) => <span key={k}>{t.label}</span>)}
        </div>
      )}
      <div className="ml-9 mr-11 mt-1.5 flex flex-wrap gap-3 sm:ml-12 sm:mr-14">
        <span className="flex items-center gap-1 text-[10px]" style={{ color: left.color }}>
          <span className="inline-block h-[2px] w-3.5" style={{ background: left.color }} />{left.label}
        </span>
        <span className="flex items-center gap-1 text-[10px]" style={{ color: right.color }}>
          <span className="inline-block h-0 w-3.5 border-t-2 border-dashed" style={{ borderColor: right.color }} />{right.label}
        </span>
      </div>
    </div>
  );
}
