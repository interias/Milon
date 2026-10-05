"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { de, de0 } from "@/lib/format";
import { finite, paceLabel } from "@/lib/garmin";
import { routeDate } from "@/lib/run-routes";
import { comparisonSegments, runInsightsApi, type ComparedRun, type ComparisonPoint, type RunComparisonData, type RunInsightCandidate } from "@/lib/run-insights";
import styles from "./RunComparison.module.css";

function extent(values: number[], step: number, fallback: [number, number]): [number, number] {
  if (!values.length) return fallback;
  const low = Math.floor(Math.min(...values) / step) * step;
  return [low, Math.max(low + 2 * step, Math.ceil(Math.max(...values) / step) * step)];
}

function ComparisonChart({ data }: { data: RunComparisonData }) {
  const ref = useRef<HTMLDivElement>(null), title = useId();
  const [width, setWidth] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  const points = useMemo(() => [...data.first.series, ...data.second.series], [data]);
  const hr = extent(points.map(point => point.hr_bpm).filter(finite), 10, [100, 180]);
  const paces = points.map(point => point.pace_seconds).filter(finite);
  const pace = extent(paces.map(value => Math.min(value, 900)), 60, [240, 600]);
  const end = Math.max(1, ...points.map(point => point.distance_m).filter(finite));
  const left = 43, right = width - 12, hrTop = 26, hrBottom = 106, paceTop = 148, paceBottom = 228;
  const x = (distance: number) => left + distance / end * (right - left);
  const yHr = (value: number) => hrBottom - (value - hr[0]) / (hr[1] - hr[0]) * (hrBottom - hrTop);
  const yPace = (value: number) => paceTop + (Math.min(value, 900) - pace[0]) / (pace[1] - pace[0]) * (paceBottom - paceTop);
  function lines(run: ComparedRun, metric: (point: ComparisonPoint) => number | null, project: (value: number) => number, second: boolean) {
    return comparisonSegments(run.series, metric).map((segment, index) => segment.length === 1
      ? <circle key={`${run.activity_id}-${index}`} cx={x(segment[0].distance)} cy={project(segment[0].value)} r="1.5" fill={second ? "#9a5b00" : "var(--color-accent)"} />
      : <path key={`${run.activity_id}-${index}`} d={segment.map((point, i) => `${i ? "L" : "M"}${x(point.distance).toFixed(2)},${project(point.value).toFixed(2)}`).join(" ")} fill="none" stroke={second ? "#9a5b00" : "var(--color-accent)"} strokeWidth="1.7" strokeDasharray={second ? "5 3" : undefined} strokeLinecap="round" strokeLinejoin="round" />);
  }
  return <div ref={ref} className={styles.chart}>
    <div className={styles.legend}><span><i />{routeDate(data.first.started_at)} · ausgewählt</span><span><i />{routeDate(data.second.started_at)} · Vergleich</span></div>
    <svg viewBox={`0 0 ${width} 261`} role="img" aria-labelledby={title}>
      <title id={title}>Zwei Läufe über gelaufene Kilometer: oben Puls, unten Pace. Ausgewählter Lauf als durchgezogene Teal-Linie, Vergleich als gestrichelte Amber-Linie. Die gleiche Distanz bedeutet nicht automatisch denselben Ort.</title>
      <text x={left} y="13" className={styles.metricLabel}>Puls · bpm</text><text x={left} y="135" className={styles.metricLabel}>Pace · min/km</text>
      {[0, .5, 1].map(fraction => <g key={fraction}>
        <line x1={left} x2={right} y1={hrTop + fraction * (hrBottom - hrTop)} y2={hrTop + fraction * (hrBottom - hrTop)} />
        <text x={left - 8} y={hrTop + fraction * (hrBottom - hrTop) + 4} textAnchor="end">{de0(hr[1] - fraction * (hr[1] - hr[0]))}</text>
        <line x1={left} x2={right} y1={paceTop + fraction * (paceBottom - paceTop)} y2={paceTop + fraction * (paceBottom - paceTop)} />
        <text x={left - 8} y={paceTop + fraction * (paceBottom - paceTop) + 4} textAnchor="end">{paceLabel(pace[0] + fraction * (pace[1] - pace[0]))}</text>
      </g>)}
      {lines(data.first, point => point.hr_bpm, yHr, false)}{lines(data.second, point => point.hr_bpm, yHr, true)}
      {lines(data.first, point => point.pace_seconds, yPace, false)}{lines(data.second, point => point.pace_seconds, yPace, true)}
      {[0, .25, .5, .75, 1].map(fraction => <text key={fraction} x={x(end * fraction)} y="251" textAnchor={fraction === 0 ? "start" : fraction === 1 ? "end" : "middle"}>{de(end * fraction / 1000, 1)}{fraction === 1 ? " km" : ""}</text>)}
    </svg>
    <p className={styles.note}>Gleiche Kilometerposition, nicht zwingend derselbe Ort. Lücken und Pausen bleiben getrennt.{paces.some(value => value > 900) ? " Pace über 15:00 /km am unteren Rand begrenzt." : ""}</p>
  </div>;
}

export function RunComparison({ activityId, candidates }: { activityId: string; candidates: RunInsightCandidate[] }) {
  const selectId = useId();
  const [open, setOpen] = useState(false), [selected, setSelected] = useState(candidates[0]?.activity_id || "");
  const [data, setData] = useState<RunComparisonData | null>(null), [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!open || !selected) return;
    const controller = new AbortController();
    setData(null); setError("");
    runInsightsApi.compare(activityId, selected, controller.signal).then(value => { if (!controller.signal.aborted) setData(value); }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Vergleich konnte nicht geladen werden."); });
    return () => controller.abort();
  }, [activityId, selected, open, revision]);
  const current = data?.first.activity_id === activityId && data.second.activity_id === selected ? data : null;
  const result = current?.comparison;
  return <details className={styles.details} onToggle={event => setOpen(event.currentTarget.open)}><summary>Läufe vergleichen <span>Puls & Tempo über die Distanz</span></summary>
    {!candidates.length ? <p className={styles.note}>Noch kein weiterer geeigneter Lauf mit vollständiger Aufzeichnung vorhanden.</p> : <>
      <label className={styles.label} htmlFor={selectId}>Vergleichslauf</label><select id={selectId} value={selected} onChange={event => setSelected(event.target.value)} className={styles.select}>{candidates.map(candidate => <option key={candidate.activity_id} value={candidate.activity_id}>{routeDate(candidate.started_at)} · {de(candidate.distance_km, 2)} km · {candidate.similarity_label}</option>)}</select>
      {error ? <p className={styles.note} role="alert">{error} <button type="button" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></p> : !current ? <p className={styles.note} role="status">Vergleich wird geladen …</p> : <>
        {result?.status === "observed" && <div className={styles.result}><div><span>Pulsdifferenz</span><strong>{finite(result.hr_delta_bpm) ? `${result.hr_delta_bpm > 0 ? "+" : ""}${de(result.hr_delta_bpm, 1)}` : "–"} <small>bpm</small></strong></div><p>Vergleich minus ausgewählter Lauf · {result.matched_pairs} passende Minutenpaare bei ähnlichem Tempo und Gefälle.</p></div>}
        <p className={styles.note}>{result?.reason}</p>
        <ComparisonChart data={current} />
        <details className={styles.method}><summary>So wird verglichen</summary><p className={styles.note}>{result?.method}</p></details>
      </>}
    </>}
  </details>;
}
