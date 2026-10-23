"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import type { CycCurve, CycRide, CycWkgHr, CycZone, CycZones } from "@/lib/api";
import { de, de0, dm } from "@/lib/format";

// Leistungszonen Z1..Z7: Set per dataviz-Validator geprüft (CVD-ΔE ≥ 10, Normalsicht ≥ 16,
// Kontrast ≥ 3:1, Lightness-Band); Farbe folgt der Zonen-Nummer, Legende nennt Namen + Watt.
export const POWER_ZONE_COLORS = ["#2a78d6", "#00917d", "#ab7f00", "#b53415", "#d4579a", "#5b3a9e", "#3a7d1e"];
export const powerZoneColor = (zone: number) => POWER_ZONE_COLORS[Math.min(7, Math.max(1, zone)) - 1];

export const EFTP_SOURCE: Record<string, string> = {
  setting: "Einstellung", "20min": "beste 20 min", fit: "Critical Power", garmin: "Garmin-FTP",
  garmin_floor: "Garmin-FTP als Untergrenze",
};

export const fmtMin = (seconds: number) => `${de0(seconds / 60)} min`;
export const fmtWhen = (iso: string) => {
  const d = new Date(iso);
  return `${d.toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" })} · ${d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}`;
};
export const hasPower = (r: CycRide) => r.avg_power != null || r.np != null;
export const rideTitle = (r: CycRide) => r.title || (r.type === "virtual_ride" ? "Zwift-Fahrt" : "Indoor-Fahrt");

export function Empty({ children, height = 120 }: { children: ReactNode; height?: number }) {
  return <div style={{ minHeight: height }} className="grid place-items-center px-2 text-center text-xs text-muted">{children}</div>;
}

// ---- Leistungskurve mit logarithmischer Zeitachse (1 s … 60 min) ----
type Pt = { seconds: number; watts: number | null };
type ValidPt = { seconds: number; watts: number };
const LOG_MAX = Math.log(3600);
const xPct = (s: number) => (Math.log(Math.max(1, s)) / LOG_MAX) * 100;
const X_TICKS: [number, string][] = [[1, "1 s"], [5, "5 s"], [15, "15 s"], [60, "1 min"], [300, "5 min"], [1200, "20 min"], [3600, "60 min"]];
const clean = (pts: Pt[]): ValidPt[] =>
  pts.filter((p): p is ValidPt => p.watts != null && p.seconds >= 1 && p.seconds <= 3600).sort((a, b) => a.seconds - b.seconds);

export function LogCurve({ lines, dots, height = 220 }: {
  lines: { label: string; color: string; dash?: string; width?: number; points: Pt[] }[];
  dots?: { label: string; color: string; points: (Pt & { date?: string | null })[] };
  height?: number;
}) {
  const ls = lines.map((l) => ({ ...l, points: clean(l.points) }));
  const dp = dots ? dots.points.filter((p): p is ValidPt & { date?: string | null } => p.watts != null && p.seconds >= 1 && p.seconds <= 3600) : [];
  const all = [...ls.flatMap((l) => l.points.map((p) => p.watts)), ...dp.map((p) => p.watts)];
  if (all.length < 2) return <Empty height={height}>keine Leistungsdaten</Empty>;
  const lo = Math.max(0, Math.floor((Math.min(...all) * 0.9) / 10) * 10), hi = Math.ceil((Math.max(...all) * 1.05) / 10) * 10;
  const y = (w: number) => 100 - ((w - lo) / (hi - lo || 1)) * 100;
  const d = (pts: ValidPt[]) => pts.map((p, k) => `${k ? "L" : "M"}${xPct(p.seconds).toFixed(2)} ${y(p.watts).toFixed(2)}`).join(" ");
  return (
    <div>
      <div className="flex" style={{ height }}>
        <div className="flex w-10 shrink-0 flex-col justify-between pr-2 text-right text-[10px] leading-none text-muted sm:w-14">
          {[hi, (hi + lo) / 2, lo].map((t, k) => <span key={k}>{de0(t)} W</span>)}
        </div>
        <div className="relative min-w-0 flex-1">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: "100%", height: "100%" }} aria-hidden>
            {[0, 0.5, 1].map((g) => <line key={g} x1="0" x2="100" y1={g * 100} y2={g * 100} stroke="var(--color-line)" strokeWidth="0.5" vectorEffect="non-scaling-stroke" />)}
            {X_TICKS.map(([s]) => <line key={s} x1={xPct(s)} x2={xPct(s)} y1="0" y2="100" stroke="var(--color-line)" strokeWidth="0.5" strokeDasharray="2 3" vectorEffect="non-scaling-stroke" />)}
            {ls.map((l) => l.points.length > 1 && <path key={l.label} d={d(l.points)} fill="none" stroke={l.color} strokeWidth={l.width ?? 2} strokeDasharray={l.dash} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />)}
          </svg>
          {dots && dp.map((p) => (
            <span key={p.seconds} title={`${dots.label} ${p.seconds < 60 ? `${p.seconds} s` : `${de0(p.seconds / 60)} min`}: ${de0(p.watts)} W${p.date ? ` · ${dm(p.date)}` : ""}`}
              className="absolute grid h-5 w-5 -translate-x-1/2 -translate-y-1/2 place-items-center" style={{ left: `${xPct(p.seconds)}%`, top: `${y(p.watts)}%` }}>
              <span className="h-2 w-2 rounded-full ring-2 ring-surface" style={{ background: dots.color }} />
            </span>
          ))}
        </div>
      </div>
      <div className="relative ml-10 mt-1 h-3 text-[10px] text-muted sm:ml-14">
        {X_TICKS.map(([s, label], k) => <span key={s} className={`absolute whitespace-nowrap ${s === 1200 ? "hidden sm:block" : ""}`} style={{ left: `${xPct(s)}%`, transform: k === 0 ? "none" : k === X_TICKS.length - 1 ? "translateX(-100%)" : "translateX(-50%)" }}>{label}</span>)}
      </div>
      <div className="ml-10 mt-2 flex flex-wrap gap-x-3 gap-y-1 sm:ml-14">
        {ls.map((l) => <span key={l.label} className="flex items-center gap-1 text-[10px] text-muted"><span className="inline-block h-0 w-3.5 border-t-2" style={{ borderColor: l.color, borderStyle: l.dash ? "dashed" : "solid" }} />{l.label}</span>)}
        {dots && dp.length > 0 && <span className="flex items-center gap-1 text-[10px] text-muted"><span className="inline-block h-2 w-2 rounded-full" style={{ background: dots.color }} />{dots.label}</span>}
      </div>
    </div>
  );
}

// ---- Puls über W/kg: Leistungszonen als Hintergrund, Puls-Zonen als Linien ----
export function WkgHrChart({ data, height = 240 }: { data: CycWkgHr; height?: number }) {
  const recent = data.periods.find((p) => p.key === "recent"), previous = data.periods.find((p) => p.key === "previous");
  const bins = data.periods.flatMap((p) => p.bins);
  if (bins.length < 2) return <Empty height={height}>noch keine Fahrt mit Leistung und gültigem Puls</Empty>;
  const xHi = Math.ceil(Math.max(...bins.map((b) => b.wkg + data.bin / 2), (data.wkg_ftp ?? 0) * 1.1) * 2) / 2;
  const yLo = Math.floor((Math.min(...bins.map((b) => b.hr_lo)) - 5) / 10) * 10, yHi = Math.ceil((Math.max(...bins.map((b) => b.hr_hi)) + 5) / 10) * 10;
  const x = (w: number) => (w / xHi) * 100, y = (h: number) => 100 - ((h - yLo) / (yHi - yLo || 1)) * 100;
  const line = (bs: CycWkgHr["periods"][number]["bins"]) => bs.map((b, k) => `${k ? "L" : "M"}${x(b.wkg).toFixed(2)} ${y(b.hr).toFixed(2)}`).join(" ");
  const band = (bs: CycWkgHr["periods"][number]["bins"]) =>
    `${bs.map((b, k) => `${k ? "L" : "M"}${x(b.wkg).toFixed(2)} ${y(b.hr_hi).toFixed(2)}`).join(" ")} ${[...bs].reverse().map((b) => `L${x(b.wkg).toFixed(2)} ${y(b.hr_lo).toFixed(2)}`).join(" ")} Z`;
  const hrLines = data.hr_zones.map((z) => z.lo_bpm).filter((b) => b > yLo && b < yHi);
  const xTicks = Array.from({ length: Math.round(xHi / 0.5) + 1 }, (_, i) => i * 0.5);
  return (
    <div>
      <div className="flex" style={{ height }}>
        <div className="flex w-10 shrink-0 flex-col justify-between pr-2 text-right text-[10px] leading-none text-muted sm:w-14">
          {[yHi, (yHi + yLo) / 2, yLo].map((t, k) => <span key={k}>{de0(t)} bpm</span>)}
        </div>
        <div className="relative min-w-0 flex-1">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: "100%", height: "100%" }} aria-hidden>
            {data.power_zones.map((z) => z.lo_wkg < xHi && (
              <rect key={z.zone} x={x(z.lo_wkg)} width={x(Math.min(z.hi_wkg ?? xHi, xHi)) - x(z.lo_wkg)} y="0" height="100" fill={powerZoneColor(z.zone)} opacity="0.1">
                <title>{`Z${z.zone} ${z.name}`}</title>
              </rect>
            ))}
            {hrLines.map((b) => <line key={b} x1="0" x2="100" y1={y(b)} y2={y(b)} stroke="var(--color-muted)" strokeWidth="0.6" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />)}
            {data.wkg_ftp != null && data.wkg_ftp < xHi && <line x1={x(data.wkg_ftp)} x2={x(data.wkg_ftp)} y1="0" y2="100" stroke="var(--color-ink)" strokeWidth="1" strokeDasharray="1 2" vectorEffect="non-scaling-stroke" />}
            {previous && previous.bins.length > 1 && <path d={line(previous.bins)} fill="none" stroke="var(--color-accent-2)" strokeWidth="1.6" strokeDasharray="4 3" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />}
            {recent && recent.bins.length > 1 && <>
              <path d={band(recent.bins)} fill="var(--color-accent)" opacity="0.15" />
              <path d={line(recent.bins)} fill="none" stroke="var(--color-accent)" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            </>}
          </svg>
          {data.hr_zones.filter((z) => z.lo_bpm > yLo && z.lo_bpm < yHi).map((z) => (
            <span key={z.zone} className="absolute right-1 -translate-y-full text-[9px] leading-none text-muted" style={{ top: `${y(z.lo_bpm)}%` }}>Puls {z.zone} ab {z.lo_bpm}</span>
          ))}
          {data.wkg_ftp != null && data.wkg_ftp < xHi && <span className="absolute top-0 -translate-x-1/2 rounded bg-surface px-1 text-[9px] leading-tight text-ink" style={{ left: `${x(data.wkg_ftp)}%` }}>FTP {de(data.wkg_ftp, 2)}</span>}
          {recent?.bins.map((b) => (
            <span key={b.wkg} title={`${de(b.wkg - data.bin / 2, 2)}–${de(b.wkg + data.bin / 2, 2)} W/kg: Median ${de0(b.hr)} bpm (${de0(b.hr_lo)}–${de0(b.hr_hi)}) · ${fmtMin(b.seconds)}`}
              className="absolute grid h-5 w-5 -translate-x-1/2 -translate-y-1/2 place-items-center" style={{ left: `${x(b.wkg)}%`, top: `${y(b.hr)}%` }}>
              <span className="h-1.5 w-1.5 rounded-full ring-2 ring-surface" style={{ background: "var(--color-accent)" }} />
            </span>
          ))}
        </div>
      </div>
      <div className="relative ml-10 mt-1 h-3 text-[10px] text-muted sm:ml-14">
        {xTicks.map((t, k) => <span key={t} className={`absolute whitespace-nowrap ${t % 1 ? "hidden sm:block" : ""}`} style={{ left: `${x(t)}%`, transform: k === 0 ? "none" : k === xTicks.length - 1 ? "translateX(-100%)" : "translateX(-50%)" }}>{de(t, 1)}</span>)}
      </div>
      <p className="mt-0.5 text-right text-[10px] text-muted">Leistung in W/kg</p>
      <div className="ml-10 mt-2 flex flex-wrap gap-x-3 gap-y-1 sm:ml-14">
        {recent && <span className="flex items-center gap-1 text-[10px] text-muted"><span className="inline-block h-0 w-3.5 border-t-2" style={{ borderColor: "var(--color-accent)" }} />{recent.label} · {recent.rides} {recent.rides === 1 ? "Fahrt" : "Fahrten"}</span>}
        {previous && <span className="flex items-center gap-1 text-[10px] text-muted"><span className="inline-block h-0 w-3.5 border-t-2 border-dashed" style={{ borderColor: "var(--color-accent-2)" }} />{previous.label} · {previous.rides} {previous.rides === 1 ? "Fahrt" : "Fahrten"}</span>}
        {data.power_zones.filter((z) => z.lo_wkg < xHi).map((z) => (
          <span key={z.zone} className="flex items-center gap-1 text-[10px] text-muted">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: powerZoneColor(z.zone), opacity: 0.45 }} />
            Z{z.zone} {z.hi_wkg != null ? `${de(z.lo_wkg, 1)}–${de(z.hi_wkg, 1)}` : `ab ${de(z.lo_wkg, 1)}`}
          </span>
        ))}
      </div>
    </div>
  );
}

export function CurveTable({ curve }: { curve: CycCurve }) {
  return (
    <details className="mt-3 text-xs text-muted">
      <summary className="cursor-pointer py-1">Werte als Tabelle</summary>
      <div className="overflow-x-auto">
        <table className="mt-2 w-full tabular-nums">
          <thead><tr className="border-b border-line text-right"><th className="pb-1 text-left font-medium">Dauer</th><th className="pb-1 font-medium">{curve.window_days} T</th><th className="pb-1 font-medium">davor</th><th className="pb-1 font-medium">Bestwert</th><th className="pb-1 font-medium">am</th></tr></thead>
          <tbody className="divide-y divide-line">
            {curve.durations.map((r) => (
              <tr key={r.seconds} className="text-right">
                <th scope="row" className="py-1 text-left font-medium text-ink">{r.label}</th>
                <td className="py-1">{r.recent != null ? `${de0(r.recent)} W` : "–"}</td>
                <td className="py-1">{r.previous != null ? `${de0(r.previous)} W` : "–"}</td>
                <td className="py-1 text-ink">{r.best != null ? `${de0(r.best)} W` : "–"}</td>
                <td className="py-1">{r.best_date ? dm(r.best_date) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

// ---- Zonen-Legende, Wochenstapel, Einzelbalken ----
export function ZoneLegend({ zones }: { zones: CycZone[] }) {
  return (
    <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1">
      {zones.map((z) => (
        <span key={z.zone} className="flex items-center gap-1 text-[10px] text-muted">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: powerZoneColor(z.zone) }} />
          Z{z.zone} {z.name} · {z.hi_w != null ? `${z.lo_w}–${z.hi_w}` : `ab ${z.lo_w}`} W
        </span>
      ))}
    </div>
  );
}

export function WeeklyZones({ data, height = 170 }: { data: CycZones; height?: number }) {
  const weeks = data.weeks;
  if (!weeks.length) return <Empty height={height}>keine Fahrten mit Leistung in diesem Zeitraum</Empty>;
  const max = Math.max(...weeks.map((w) => w.total), 1);
  const stride = Math.max(1, Math.ceil(weeks.length / 7));
  const labelH = 18, plotH = height - labelH - 4; // 4 px = mt-1 des Datumslabels
  return (
    <div>
      <div className="flex" style={{ height }}>
        <div className="flex w-10 shrink-0 flex-col justify-between pr-2 text-right text-[10px] leading-none text-muted sm:w-14" style={{ paddingBottom: labelH + 4 }}>
          {[max, max / 2, 0].map((t, k) => <span key={k}>{de0(t / 60)} min</span>)}
        </div>
        <div className="flex min-w-0 flex-1 items-end gap-1.5">
          {weeks.map((w, i) => (
            <div key={w.week} className="flex min-w-0 flex-1 flex-col items-center justify-end" style={{ height }}>
              <div className="flex w-full flex-col-reverse overflow-hidden rounded-t" style={{ height: Math.max(2, (w.total / max) * plotH) }}>
                {w.seconds.map((s, zi) => s > 0 && <div key={zi} title={`Woche ${dm(w.week)} · Z${zi + 1}: ${fmtMin(s)}`} style={{ height: `${(s / w.total) * 100}%`, background: powerZoneColor(zi + 1), borderTop: "2px solid var(--color-surface)" }} />)}
              </div>
              <span className="mt-1 w-full whitespace-nowrap text-center text-[9px] leading-none text-muted" style={{ height: labelH }}>{i % stride === 0 || i === weeks.length - 1 ? dm(w.week) : ""}</span>
            </div>
          ))}
        </div>
      </div>
      <ZoneLegend zones={data.zones} />
      <details className="mt-3 text-xs text-muted">
        <summary className="cursor-pointer py-1">Werte als Tabelle (Minuten)</summary>
        <div className="overflow-x-auto">
          <table className="mt-2 w-full tabular-nums">
            <thead><tr className="border-b border-line text-right"><th className="pb-1 text-left font-medium">Woche</th>{data.zones.map((z) => <th key={z.zone} className="pb-1 font-medium">Z{z.zone}</th>)}</tr></thead>
            <tbody className="divide-y divide-line">
              {weeks.map((w) => <tr key={w.week} className="text-right"><th scope="row" className="py-1 text-left font-medium text-ink">{dm(w.week)}</th>{w.seconds.map((s, i) => <td key={i} className="py-1">{de0(s / 60)}</td>)}</tr>)}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

export function RideZoneBar({ zones }: { zones: (CycZone & { seconds: number | null })[] }) {
  const total = zones.reduce((a, z) => a + (z.seconds ?? 0), 0);
  if (!zones.length || total <= 0) return <Empty>keine Zonen-Daten (Leistung oder eFTP fehlt)</Empty>;
  return (
    <div>
      <div className="flex h-6 w-full overflow-hidden rounded">
        {zones.map((z) => (z.seconds ?? 0) > 0 && <div key={z.zone} title={`Z${z.zone} ${z.name}: ${fmtMin(z.seconds as number)}`} style={{ width: `${((z.seconds as number) / total) * 100}%`, background: powerZoneColor(z.zone), borderLeft: "2px solid var(--color-surface)" }} />)}
      </div>
      <table className="mt-3 w-full text-xs tabular-nums">
        <tbody className="divide-y divide-line">
          {zones.map((z) => (
            <tr key={z.zone}>
              <td className="py-1.5"><span className="mr-2 inline-block h-2.5 w-2.5 rounded-sm align-middle" style={{ background: powerZoneColor(z.zone) }} />Z{z.zone} {z.name}</td>
              <td className="py-1.5 text-right text-muted">{z.hi_w != null ? `${z.lo_w}–${z.hi_w}` : `ab ${z.lo_w}`} W</td>
              <td className="py-1.5 text-right font-semibold">{fmtMin(z.seconds ?? 0)}</td>
              <td className="w-12 py-1.5 text-right text-muted">{de0(((z.seconds ?? 0) / total) * 100)} %</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---- Fahrt-Zeile (Liste) ----
export function RideRow({ r }: { r: CycRide }) {
  const power = hasPower(r);
  const hr = r.avg_hr != null && r.hr_valid ? ` · ${de0(r.avg_hr)} bpm` : "";
  return (
    <Link href={`/rad/${encodeURIComponent(r.activity_id)}`} className="block py-3 hover:bg-surface-alt/60 sm:px-1">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{rideTitle(r)}</p>
          <p className="truncate text-[11px] text-muted">{fmtWhen(r.date)}{r.world ? ` · ${r.world}` : ""}{r.route ? ` · ${r.route}` : ""}</p>
        </div>
        <span className="shrink-0 text-xs font-semibold text-accent">Details →</span>
      </div>
      <p className="mt-1 text-xs tabular-nums text-muted">
        {de0(r.minutes)} min{r.km != null ? ` · ${de(r.km, 1)} km` : ""}
        {power ? ` · Ø ${de0(r.avg_power)} W · NP ${de0(r.np)} W${r.tss != null ? ` · TSS ${de0(r.tss)}` : ""}` : ""}{hr}
        {!power && <> · <span className="rounded-full border border-line bg-surface-alt px-2 py-0.5 text-[10px] font-semibold">ohne Leistungsdaten</span></>}
      </p>
    </Link>
  );
}
