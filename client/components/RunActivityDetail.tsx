"use client";

import { useEffect, useId, useMemo, useRef, useState, type PointerEvent } from "react";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { activitySegments, finite, garminApi, nearestActivityPoint, paceLabel, paceSeconds, type GarminActivity, type GarminActivityPoint } from "@/lib/garmin";
import { routeDate } from "@/lib/run-routes";
import { de, de0, dur } from "@/lib/format";
import styles from "./RunActivityDetail.module.css";

function bounds(values: number[], step: number, fallback: [number, number]) {
  if (!values.length) return fallback;
  const low = Math.floor(Math.min(...values) / step) * step;
  return [low, Math.max(low + step * 2, Math.ceil(Math.max(...values) / step) * step)] as [number, number];
}

function ActivityChart({ points }: { points: GarminActivityPoint[] }) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(620), [selected, setSelected] = useState<number | null>(null);
  const [showHeight, setShowHeight] = useState(false);
  const chartId = useId();
  useEffect(() => {
    if (!container.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(180, entry.contentRect.width)));
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  const series = useMemo(() => points.filter(point => finite(point.elapsed_seconds)).sort((a, b) => a.elapsed_seconds - b.elapsed_seconds), [points]);
  const hasHeight = series.some(point => finite(point.altitude_m));
  const hasHr = series.some(point => finite(point.hr_bpm));
  const hasPace = series.some(point => finite(paceSeconds(point.speed_m_s)));
  const hrRange = bounds(series.map(point => point.hr_bpm).filter(finite), 10, [80, 180]);
  const allPaces = series.map(point => paceSeconds(point.speed_m_s)).filter(finite);
  const paceRange = bounds(allPaces.map(value => Math.min(value, 900)), 60, [240, 600]);
  if (paceRange[0] >= 900) { paceRange[0] = 780; paceRange[1] = 900; }
  const clippedPace = allPaces.some(value => value > 900);
  const heightRange = bounds(series.map(point => point.altitude_m).filter(finite), 10, [0, 100]);
  const left = 43, right = Math.max(left + 50, width - 43), top = 26, bottom = 206;
  const heightTop = 237, heightBottom = 299;
  const withHeight = showHeight && hasHeight, axisBottom = withHeight ? heightBottom : bottom;
  const svgHeight = axisBottom + 34;
  const end = Math.max(1, series.at(-1)?.elapsed_seconds ?? 1);
  const x = (time: number) => left + time / end * (right - left);
  const yHr = (value: number) => bottom - (value - hrRange[0]) / (hrRange[1] - hrRange[0]) * (bottom - top);
  const yPace = (value: number) => top + (Math.min(value, 900) - paceRange[0]) / (paceRange[1] - paceRange[0]) * (bottom - top);
  const yHeight = (value: number) => heightBottom - (value - heightRange[0]) / (heightRange[1] - heightRange[0]) * (heightBottom - heightTop);
  const active = selected == null ? null : series[Math.min(selected, series.length - 1)];
  const ticks = width < 420 ? 3 : 5;
  function selectPoint(event: PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const relative = (event.clientX - rect.left) / rect.width * width;
    setSelected(nearestActivityPoint(series, Math.max(0, Math.min(end, (relative - left) / (right - left) * end))));
  }
  function lines(value: (point: GarminActivityPoint) => number | null, project: (value: number) => number, className: string) {
    return activitySegments(series, value).map((segment, index) => segment.length === 1
      ? <circle key={`${className}-${index}`} cx={x(segment[0].time)} cy={project(segment[0].value)} r="1.7" fill="white" className={className} />
      : <path key={`${className}-${index}`} d={segment.map((point, i) => `${i ? "L" : "M"}${x(point.time).toFixed(2)},${project(point.value).toFixed(2)}`).join(" ")} className={className} fill="none" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />);
  }
  return <div ref={container} className={styles.chart}>
    <div className={styles.chartHeader}><h3>Puls & Tempo</h3>{hasHeight && <label><input type="checkbox" checked={showHeight} onChange={event => setShowHeight(event.target.checked)} />Höhenprofil</label>}</div>
    <div className={styles.legend}><span className={styles.hrKey}>Herzfrequenz · links</span><span className={styles.paceKey}>Pace · rechts</span><span>Zeit ab Start · inkl. Pausen</span></div>
    {!series.length || (!hasHr && !hasPace) ? <p className={styles.empty}>Für diesen Lauf sind noch keine Puls- oder Tempowerte verfügbar.</p> : <>
      <svg viewBox={`0 0 ${width} ${svgHeight}`} height={svgHeight} role="group" tabIndex={0} aria-labelledby={chartId} className={styles.plot}
        onPointerMove={selectPoint} onPointerDown={event => { event.currentTarget.focus(); selectPoint(event); }}
        onKeyDown={event => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
          if (event.key === "Escape" && selected == null) return;
          event.preventDefault(); event.stopPropagation();
          if (event.key === "Escape") { setSelected(null); return; }
          if (event.key === "Home") { setSelected(0); return; }
          if (event.key === "End") { setSelected(series.length - 1); return; }
          setSelected(previous => Math.max(0, Math.min(series.length - 1, previous == null ? event.key === "ArrowRight" ? 0 : series.length - 1 : previous + (event.key === "ArrowRight" ? 1 : -1))));
        }}>
        <title id={chartId}>Puls und Pace auf gemeinsamer Zeitachse. Links Herzfrequenz in bpm, rechts Minuten pro Kilometer, schnelleres Tempo oben. Pfeiltasten wählen Zeitpunkte.</title>
        <text x={left - 8} y="13" textAnchor="end" className={styles.hrText}>bpm</text><text x={right + 8} y="13" className={styles.paceText}>/km</text>
        {[0, .25, .5, .75, 1].map(fraction => <g key={fraction}>
          <line x1={left} x2={right} y1={top + fraction * (bottom - top)} y2={top + fraction * (bottom - top)} className={styles.grid} />
          <text x={left - 8} y={top + fraction * (bottom - top) + 4} textAnchor="end" className={styles.hrText}>{hasHr ? de0(hrRange[1] - fraction * (hrRange[1] - hrRange[0])) : "–"}</text>
          <text x={right + 8} y={top + fraction * (bottom - top) + 4} className={styles.paceText}>{hasPace ? paceLabel(paceRange[0] + fraction * (paceRange[1] - paceRange[0])) : "–"}</text>
        </g>)}
        {lines(point => paceSeconds(point.speed_m_s), yPace, styles.paceLine)}
        {lines(point => point.hr_bpm, yHr, styles.hrLine)}
        {withHeight && <>
          <rect x={left} y={heightTop} width={right - left} height={heightBottom - heightTop} fill="#f4f6f7" rx="3" />
          <text x={left} y={heightTop - 7} className={styles.axisText}>Höhe · m</text>
          {[0, 1].map(fraction => <text key={fraction} x={left - 8} y={heightTop + fraction * (heightBottom - heightTop) + 4} textAnchor="end" className={styles.axisText}>{de0(heightRange[1] - fraction * (heightRange[1] - heightRange[0]))}</text>)}
          {lines(point => point.altitude_m, yHeight, styles.heightLine)}
        </>}
        {Array.from({ length: ticks }, (_, index) => <text key={index} x={left + index / (ticks - 1) * (right - left)} y={axisBottom + 23} textAnchor={index === 0 ? "start" : index === ticks - 1 ? "end" : "middle"} className={styles.axisText}>{dur(end * index / (ticks - 1))}</text>)}
        {active && <>
          <line x1={x(active.elapsed_seconds)} x2={x(active.elapsed_seconds)} y1={top} y2={axisBottom} className={styles.cursor} />
          {finite(active.hr_bpm) && <circle cx={x(active.elapsed_seconds)} cy={yHr(active.hr_bpm)} r="4" fill="white" className={styles.hrLine} strokeWidth="2" />}
          {finite(paceSeconds(active.speed_m_s)) && <circle cx={x(active.elapsed_seconds)} cy={yPace(paceSeconds(active.speed_m_s)!)} r="4" fill="white" className={styles.paceLine} strokeWidth="2" />}
        </>}
      </svg>
      <div className={styles.readout} role="status" aria-live="polite">{active ? <>
        <strong>{dur(active.elapsed_seconds)}</strong><span className={styles.hrText}>{de0(active.hr_bpm)} bpm</span><span className={styles.paceText}>{active.speed_m_s === 0 ? "Stillstand" : `${paceLabel(paceSeconds(active.speed_m_s))} /km`}</span>
        {finite(active.distance_m) && <span>{de(active.distance_m / 1000, 2)} km</span>}{withHeight && <span>{de0(active.altitude_m)} m Höhe</span>}
      </> : <span>Berühren oder mit ← → erkunden · beide Werte am selben Zeitpunkt</span>}</div>
      <p className={styles.note}>Zwei getrennte Werteskalen. Lücken und Stillstand unterbrechen die Tempokurve.{clippedPace ? " Pace über 15:00 /km liegt am unteren Rand; die Auswahl zeigt den genauen Wert." : ""}</p>
    </>}
  </div>;
}

function ActivityContent({ data }: { data: GarminActivity }) {
  const summary = data.summary;
  const averagePace = finite(summary.distance_km) && summary.distance_km > 0 && finite(summary.duration_seconds) ? summary.duration_seconds / summary.distance_km : null;
  const dynamics = [
    ["Kadenz", summary.avg_cadence_spm, "Schritte/min", 0], ["Laufleistung", summary.avg_power_w, "W", 0],
    ["Bodenkontakt", summary.ground_contact_ms, "ms", 0], ["Schrittlänge", summary.stride_length_cm, "cm", 0],
    ["Vertikale Bewegung", summary.vertical_oscillation_cm, "cm", 1], ["Vertikales Verhältnis", summary.vertical_ratio_pct, "%", 1],
  ] as const;
  const visibleDynamics = dynamics.filter(([, value]) => finite(value));
  return <>
    <div className={styles.intro}><div><h3>{summary.title || "Lauf"}</h3><p>{routeDate(summary.started_at)}</p></div><span className={styles.source}>Garmin direkt</span></div>
    <div className={styles.summary}>
      <div><span>Distanz</span><strong>{de(summary.distance_km, 2)} <small>km</small></strong></div>
      <div><span>Ø Pace</span><strong>{paceLabel(averagePace)} <small>/km</small></strong></div>
      <div><span>Ø Puls</span><strong>{de0(summary.avg_hr)} <small>bpm</small></strong></div>
      <div><span>Aktive Dauer</span><strong>{dur(summary.duration_seconds)}</strong></div>
    </div>
    <ActivityChart key={data.activity_id} points={data.series} />
    {data.laps.length > 0 && <details className={styles.details}><summary>Runden <span>{data.laps.length} · Distanz, Tempo & Puls</span></summary>
      <div className={styles.tableWrap}><table><caption className="sr-only">Von Garmin aufgezeichnete Runden</caption><thead><tr><th>Runde</th><th>km</th><th>Dauer</th><th>Pace /km</th><th>Ø bpm</th></tr></thead><tbody>
        {data.laps.map((lap, index) => <tr key={`${lap.index}-${index}`}><th>{lap.index}</th><td>{finite(lap.distance_m) ? de(lap.distance_m / 1000, 2) : "–"}</td><td>{dur(lap.duration_seconds)}</td><td>{paceLabel(finite(lap.distance_m) && lap.distance_m > 0 && finite(lap.duration_seconds) ? lap.duration_seconds * 1000 / lap.distance_m : null)}</td><td>{de0(lap.avg_hr)}</td></tr>)}
      </tbody></table></div>
      <p className={styles.note}>Originalrunden der Uhr; je nach Aufzeichnung auch andere Distanzen als 1 km.</p>
    </details>}
    {visibleDynamics.length > 0 && <details className={styles.details}><summary>Laufdynamik <span>Durchschnittswerte</span></summary><dl className={styles.dynamics}>{visibleDynamics.map(([label, value, unit, decimals]) => <div key={label}><dt>{label}</dt><dd>{de(value, decimals)} <span>{unit}</span></dd></div>)}</dl></details>}
    <details className={styles.details}><summary>Datenbasis <span>{de0(data.quality.points)} Messpunkte</span></summary>
      <p className={styles.note}>Zeitabdeckung: Puls {de0(data.quality.hr_coverage * 100)} % · Tempo {de0(data.quality.speed_coverage * 100)} % der aktiven Dauer. Das Diagramm zeigt eine ausgedünnte Darstellung; für die Analyse bleibt die vollständige Aufzeichnung gespeichert.</p>
      {!data.quality.complete && <p className={styles.note}>Die Aufzeichnung ist unvollständig. Fehlende Werte bleiben als Lücken sichtbar.</p>}
      {!data.quality.canonical && <p className={styles.note}>Diese Aufzeichnung ergänzt die Details. Sie ersetzt die bisherigen Laufwerte noch nicht.</p>}
      {data.quality.last_issue && <p className={styles.note}>Beim letzten Abruf war die Aufzeichnung unvollständig. Hier bleibt der vorherige vollständige Stand erhalten.</p>}
    </details>
  </>;
}

export function RunActivityDetail({ activityId, onClose }: { activityId: string; onClose: () => void }) {
  const [data, setData] = useState<GarminActivity | null>(null), [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const refresh = () => setRevision(value => value + 1);
    window.addEventListener("milon:data-refresh", refresh);
    return () => window.removeEventListener("milon:data-refresh", refresh);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError("");
    garminApi.activity(activityId, controller.signal).then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Laufdetails konnten nicht geladen werden."); });
    return () => controller.abort();
  }, [activityId, revision]);
  return <RunAnalysisDialog title="Laufdetails" onClose={onClose}><div className={styles.content}>
    {error ? <div className={styles.empty} role="alert"><p>{error}</p><button type="button" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></div>
      : !data || data.activity_id !== activityId ? <p className={styles.empty} role="status">Laufdetails werden geladen …</p>
        : !data.available ? <div className={styles.empty}><p>Für diesen Lauf wurden noch keine Detaildaten importiert.</p><p>Schließe dieses Fenster und wähle „Garmin aktualisieren“.</p></div>
          : <ActivityContent data={data} />}
  </div></RunAnalysisDialog>;
}
