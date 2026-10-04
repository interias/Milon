"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { api, type SleepOverview, type SleepPerformance, type SleepPerformancePoint } from "@/lib/api";
import { RunTrendChart } from "@/components/RunTrendChart";
import { Card } from "@/components/ui";
import { de, dm } from "@/lib/format";

const dateLabel = (value: string) => new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString("de-DE");

function sleepTrend(data: SleepOverview) {
  const nights = data.series.filter((point) => point.main_sleep);
  if (!nights.length) return [];
  const byDay = new Map(nights.map((night) => [night.date, night]));
  const dates = [...byDay.keys()].sort();
  const start = new Date(`${dates[0]}T12:00:00Z`);
  const end = new Date(`${dates[dates.length - 1]}T12:00:00Z`);
  const points = [];
  for (const day = new Date(start); day <= end; day.setUTCDate(day.getUTCDate() + 1)) {
    const date = day.toISOString().slice(0, 10);
    const night = byDay.get(date);
    const label = data.sources.find((source) => source.package === night?.source_package)?.label;
    points.push({ date, value: night?.asleep_hours ?? null, segment_id: night?.source_package,
      detail: night ? `${label ?? "Uhr"} · Schlaffenster ${de(night.window_hours, 2)} h · ${de(night.awake_minutes, 0)} min wach` : "Keine Nacht erfasst" });
  }
  return points;
}

function axis(values: number[]) {
  const min = Math.min(...values), max = Math.max(...values);
  const padding = Math.max((max - min) * 0.12, Math.abs(max) * 0.02, 0.1);
  const low = min - padding, high = max + padding;
  return { low, high, ticks: Array.from({ length: 5 }, (_, index) => low + index * (high - low) / 4) };
}

function SleepScatter({ points, unit, label }: { points: SleepPerformancePoint[]; unit: string; label: string }) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(300);
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => {
    if (!container.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(1, entry.contentRect.width)));
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  const sorted = [...points].filter((point) => Number.isFinite(point.sleep_hours) && Number.isFinite(point.value))
    .sort((a, b) => a.date.localeCompare(b.date));
  if (!sorted.length) return <div ref={container} className="py-6 text-sm text-muted">Noch keine Nacht mit passendem Training und bekannter Schlafdauer.</div>;
  const horizontal = axis(sorted.map((point) => point.sleep_hours));
  const vertical = axis(sorted.map((point) => point.value));
  const left = 62, right = Math.max(left + 20, width - 16), top = 26, bottom = 234;
  const x = (value: number) => left + (value - horizontal.low) / (horizontal.high - horizontal.low) * (right - left);
  const y = (value: number) => bottom - (value - vertical.low) / (vertical.high - vertical.low) * (bottom - top);
  const active = selected == null ? null : sorted[Math.min(selected, sorted.length - 1)];
  const xTicks = width < 420 ? horizontal.ticks.filter((_, index) => index % 2 === 0) : horizontal.ticks;
  function selectPoint(event: PointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const px = (event.clientX - bounds.left) / bounds.width * width;
    const py = (event.clientY - bounds.top) / bounds.height * 292;
    let nearest = 0, distance = Infinity;
    sorted.forEach((point, index) => {
      const next = Math.hypot(x(point.sleep_hours) - px, y(point.value) - py);
      if (next < distance) { nearest = index; distance = next; }
    });
    setSelected(nearest);
  }
  return <div ref={container} className="mt-3 min-w-0">
    <svg viewBox={`0 0 ${width} 292`} height="292" className="w-full rounded outline-accent" role="group" tabIndex={0}
      aria-label={`${label}. X-Achse Schlafdauer in Stunden, Y-Achse ${unit}. Pfeiltasten wählen Nächte nach Datum.`}
      onKeyDown={(event) => {
        if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "Escape"].includes(event.key)) return;
        event.preventDefault();
        if (event.key === "Escape") { setSelected(null); return; }
        if (event.key === "Home") { setSelected(0); return; }
        if (event.key === "End") { setSelected(sorted.length - 1); return; }
        const forward = event.key === "ArrowRight" || event.key === "ArrowDown";
        setSelected((previous) => Math.max(0, Math.min(sorted.length - 1,
          previous == null ? forward ? 0 : sorted.length - 1 : previous + (forward ? 1 : -1))));
      }} onPointerMove={selectPoint} onPointerDown={(event) => { event.currentTarget.focus(); selectPoint(event); }}>
      <text x={left} y="14" fontSize="12" fill="var(--color-muted)">{unit}</text>
      {vertical.ticks.map((tick, index) => <g key={index}>
        <line x1={left} x2={right} y1={y(tick)} y2={y(tick)} stroke="var(--color-line)" />
        <text x={left - 9} y={y(tick) + 4} textAnchor="end" fontSize="12" fill="var(--color-muted)">{de(tick, unit === "%" ? 1 : 2)}</text>
      </g>)}
      {vertical.low < 0 && vertical.high > 0 && <line x1={left} x2={right} y1={y(0)} y2={y(0)} stroke="var(--color-muted)" strokeDasharray="4 4" />}
      {xTicks.map((tick, index) => <text key={index} x={x(tick)} y="255" textAnchor="middle" fontSize="12" fill="var(--color-muted)">{de(tick, 1)}</text>)}
      <text x={(left + right) / 2} y="282" textAnchor="middle" fontSize="12" fill="var(--color-muted)">Schlafdauer · Stunden</text>
      {sorted.map((point, index) => <circle key={`${point.date}-${point.session_id}`} cx={x(point.sleep_hours)} cy={y(point.value)} r={selected === index ? 6 : 4}
        fill={selected === index ? "var(--color-surface)" : "var(--color-accent)"} stroke="var(--color-accent)" strokeWidth={selected === index ? 2 : 1}>
        <title>{dateLabel(point.date)} · {de(point.sleep_hours, 2)} h · {de(point.value, 2)} {unit} · {point.title}</title>
      </circle>)}
    </svg>
    <div className="min-h-12 rounded border border-line bg-surface-alt px-3 py-2 text-xs" role="status" aria-live="polite">
      {active ? <><p className="font-semibold">{dateLabel(active.date)} · {de(active.sleep_hours, 2)} h Schlaf · {de(active.value, 2)} {unit}</p>
        <p className="mt-1 break-words text-muted">{active.title}</p></> : <p className="text-muted">Punkt berühren oder Diagramm mit den Pfeiltasten erkunden.</p>}
    </div>
  </div>;
}

export function SleepPanel() {
  const [overview, setOverview] = useState<SleepOverview | null>(null);
  const [overviewError, setOverviewError] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [kind, setKind] = useState<"run" | "strength">("run");
  const [source, setSource] = useState("current");
  const [performance, setPerformance] = useState<SleepPerformance | null>(null);
  const [performanceError, setPerformanceError] = useState(false);
  useEffect(() => {
    let active = true;
    api.sleepOverview(90).then((data) => { if (active) setOverview(data); }).catch(() => { if (active) setOverviewError(true); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!expanded) return;
    let active = true;
    setPerformance(null);
    setPerformanceError(false);
    api.sleepPerformance(kind, source, 180).then((data) => { if (active) setPerformance(data); }).catch(() => { if (active) setPerformanceError(true); });
    return () => { active = false; };
  }, [expanded, kind, source]);
  const result = performance?.kind === kind && performance.source === source ? performance : null;
  const summary = overview?.summary;
  const unknown = overview?.series.filter((point) => point.main_sleep && point.asleep_hours == null) ?? [];
  return <Card className="mt-4">
    <h2 className="text-sm font-semibold">Schlaf & Erholung</h2>
    {summary ? <>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div><p className="text-xs text-muted">Letzte erfasste Nacht</p><p className="mt-1 font-display text-2xl font-extrabold">{de(summary.latest_asleep_hours, 2)} <span className="text-sm font-normal text-muted">h Schlaf</span></p>
          <p className="mt-1 text-xs text-muted">{summary.latest_date ? dateLabel(summary.latest_date) : "Noch keine Nacht erfasst"}{summary.latest_date && summary.latest_asleep_hours == null ? " · Schlafdauer unbekannt" : ""}</p>
          {summary.latest_date && <p className="mt-1 text-xs text-muted">Schlaffenster {de(summary.latest_window_hours, 2)} h</p>}</div>
        <div><p className="text-xs text-muted">Aktuelle Uhr · letzte 7 Tage</p><p className="mt-1 font-display text-2xl font-extrabold">{de(summary.avg_asleep_hours_7d, 2)} <span className="text-sm font-normal text-muted">h im Mittel</span></p>
          <p className="mt-1 text-xs text-muted">{summary.known_asleep_nights_7d} bekannte / {summary.nights_7d} erfasste Nächte · 7 Kalendertage</p></div>
        <div><p className="text-xs text-muted">Separat erfasst · letzte 7 Tage</p><p className="mt-1 font-display text-2xl font-extrabold">{summary.naps_7d} <span className="text-sm font-normal text-muted">Nickerchen</span></p>
          <p className="mt-1 text-xs text-muted">Kein Teil des Nachtmittels</p></div>
      </div>
      <div className="mt-5 border-t border-line pt-3"><h3 className="text-xs font-semibold">Erfasste Schlafdauer · bis zu 90 Tage</h3>
        <RunTrendChart label="Schlafdauer der Hauptnächte" unit="h" points={sleepTrend(overview!)} />
        <p className="mt-2 text-xs text-muted">Lücken bleiben unbekannt.{overview?.switch_date ? ` Gerätewechsel am ${dateLabel(overview.switch_date)}; die Kurve wird getrennt.` : ""}</p>
      </div>
      {unknown.length > 0 && <details className="mt-3 text-xs text-muted"><summary className="cursor-pointer py-1">{unknown.length} Nächte nur mit Schlaffenster · Schlafdauer unbekannt</summary>
        <p className="mt-1">Diese Zeiten werden im Schlafdiagramm und bei Korrelationen ausgelassen.</p>
        <ul className="mt-2 space-y-1">{unknown.slice(-5).reverse().map((night) => <li key={night.external_id}>{dateLabel(night.date)} · {de(night.window_hours, 2)} h Schlaffenster</li>)}</ul>
      </details>}
    </> : <p className="mt-3 text-xs text-muted" role="status">{overviewError ? "Schlafdaten konnten nicht geladen werden." : "Schlafdaten werden geladen …"}</p>}
    <button type="button" aria-expanded={expanded} aria-controls="sleep-performance" onClick={() => setExpanded((value) => !value)} className="mt-4 rounded border border-line px-3 py-2 text-sm outline-accent">Schlaf ↔ Leistung {expanded ? "schließen" : "erkunden"}</button>
    {expanded && <section id="sleep-performance" className="mt-4 border-t border-line pt-4">
      <h3 className="text-sm font-semibold">Wie hängt die vorige Nacht mit deinem Training zusammen?</h3>
      <div className="mt-3 flex flex-wrap gap-3">
        <label className="text-xs text-muted">Training<select value={kind} onChange={(event) => setKind(event.target.value as "run" | "strength")} className="mt-1 block rounded border border-line bg-surface px-3 py-2 text-base text-ink outline-accent sm:text-sm"><option value="run">Laufen</option><option value="strength">Kraft</option></select></label>
        <label className="text-xs text-muted">Uhr<select value={source} onChange={(event) => setSource(event.target.value)} className="mt-1 block rounded border border-line bg-surface px-3 py-2 text-base text-ink outline-accent sm:text-sm"><option value="current">Aktuelle Uhr</option><option value="legacy">Vorherige Uhr</option><option value="all">Beide, getrennt</option></select></label>
      </div>
      {result ? <>
        <p className="mt-3 text-xs text-muted">{result.outcome_label} · höhere Werte bedeuten bessere gemessene Leistung · letzte 180 Kalendertage</p>
        <div className="mt-4 space-y-5">{result.groups.map((group) => {
          const missing = Object.values(group.missing).reduce((total, count) => total + count, 0);
          return <div key={`${kind}-${group.package}`} className="rounded border border-line p-3 sm:p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2"><h4 className="text-sm font-semibold">{group.label} · {group.n} Nacht-Training-Paare</h4>
              <p className="text-sm font-semibold">r = {de(group.correlation, 2)}</p></div>
            <p className="mt-2 text-xs text-muted">{group.status_label}</p>
            {group.ci95 && <p className="mt-1 text-xs text-muted">95%-Näherungsintervall für r: {de(group.ci95[0], 2)} bis {de(group.ci95[1], 2)}</p>}
            <SleepScatter points={group.points} label={`Schlaf und ${kind === "run" ? "Laufeffizienz" : "Kraftentwicklung"} · ${group.label}`} unit={result.outcome_unit} />
            <details className="mt-3 text-xs text-muted"><summary className="cursor-pointer py-1">Datenabdeckung · {missing} Einheiten ohne verwendbares Paar</summary>
              <p className="mt-1">{group.missing.no_sleep} ohne vorherigen Hauptschlaf · {group.missing.unknown_sleep} mit unbekannter Schlafdauer · {group.missing.no_outcome} ohne geeigneten Leistungswert · {group.missing.excluded} ausgeschlossen</p>
              <p className="mt-1">Mehrere Trainings am selben Tag zählen zusammen als ein Nacht-Paar.</p>
            </details>
          </div>;
        })}</div>
        <p className="mt-4 text-xs leading-relaxed text-muted">{result.caveat}</p>
        <details className="mt-3 text-xs text-muted"><summary className="cursor-pointer py-1">So berechnen wir die Paare</summary><p className="mt-2 leading-relaxed">{result.method}</p></details>
      </> : <p className="mt-4 text-xs text-muted" role="status">{performanceError ? "Die Auswertung konnte nicht geladen werden." : "Auswertung wird geladen …"}</p>}
    </section>}
    {overview && <details className="mt-3 text-xs text-muted"><summary className="cursor-pointer py-1">Wie wir Schlaf erfassen</summary><p className="mt-2 leading-relaxed">{overview.method}</p>{overview.notes.map((note) => <p key={note} className="mt-1">{note}</p>)}</details>}
  </Card>;
}
