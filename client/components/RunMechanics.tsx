"use client";

import { useEffect, useId, useRef, useState } from "react";
import { mechanicsApi, type MechanicsMetric, type RunMechanicsData } from "@/lib/run-mechanics";
import { de } from "@/lib/format";
import styles from "./RunMechanics.module.css";

const value = (number: number | null, unit: string) => number == null ? "–" : de(number, unit === "spm" || unit === "ms" ? 1 : 2);
const change = (number: number | null, unit: string) => number == null ? "–" : `${number > 0 ? "+" : ""}${value(number, unit)}`;

function MechanicsChart({ metric, midpoint }: { metric: MechanicsMetric; midpoint: number }) {
  const id = useId();
  const host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(590);
  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(250, entry.contentRect.width)));
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  const points = metric.series;
  if (!points.length) return <div ref={host}><p className={styles.empty}>Für diese Kennzahl fehlen geeignete Minuten mit vollständiger Messung.</p></div>;
  const numbers = points.map(point => point.value), minimum = Math.min(...numbers), maximum = Math.max(...numbers);
  const span = Math.max(maximum - minimum, metric.unit === "%" ? .4 : 2);
  const low = minimum - span * .2, high = maximum + span * .2;
  const start = points[0].minute, end = points.at(-1)!.minute;
  const right = width - 20;
  const x = (minute: number) => 40 + (minute - start) / Math.max(1, end - start) * (right - 40);
  const y = (number: number) => 110 - (number - low) / (high - low) * 92;
  let previous: number | null = null;
  const path = points.map(point => {
    const move = previous == null || point.minute - previous > 1.01;
    previous = point.minute;
    return `${move ? "M" : "L"}${x(point.minute).toFixed(1)},${y(point.value).toFixed(1)}`;
  }).join(" ");
  return <div ref={host}><svg className={styles.chart} viewBox={`0 0 ${width} 138`} role="img" aria-labelledby={id}>
    <title id={id}>{metric.label} über geeignete Laufminuten. Früh {value(metric.early, metric.unit)}, spät {value(metric.late, metric.unit)} {metric.unit} in vergleichbaren Abschnitten.</title>
    <rect x="40" y="12" width={right - 40} height="104" fill="#f7faf9" rx="4" />
    {[minimum, maximum].filter((item, index, list) => index === 0 || item !== list[0]).map(number => <g key={number}><line x1="40" x2={right} y1={y(number)} y2={y(number)} stroke="#e2e7e8" strokeDasharray="2 4" /><text x="34" y={y(number) + 3} textAnchor="end">{value(number, metric.unit)}</text></g>)}
    {midpoint > start && midpoint < end && <line x1={x(midpoint)} x2={x(midpoint)} y1="12" y2="116" stroke="#9bb7b1" strokeDasharray="3 4" />}
    <path d={path} fill="none" stroke="#0a6e66" strokeWidth="1.7" strokeLinejoin="round" />
    {points.map(point => <circle key={point.minute} cx={x(point.minute)} cy={y(point.value)} r="1.7" fill="#0a6e66" />)}
    {[start, ...(end - start > 5 ? [(start + end) / 2] : []), ...(end > start ? [end] : [])].map(minute => <text key={minute} x={x(minute)} y="132" textAnchor="middle">{de(minute, 0)} min</text>)}
  </svg></div>;
}

export function RunMechanics({ activityId }: { activityId: string }) {
  const [data, setData] = useState<RunMechanicsData | null>(null), [error, setError] = useState("");
  const [selected, setSelected] = useState("step_speed_loss_pct"), [revision, setRevision] = useState(0);
  const selectId = useId();
  useEffect(() => {
    const controller = new AbortController();
    setError(""); setData(null);
    mechanicsApi.activity(activityId, controller.signal).then(result => {
      if (!controller.signal.aborted) setData(result);
    }).catch(reason => { if (!controller.signal.aborted) setError(String(reason)); });
    return () => controller.abort();
  }, [activityId, revision]);
  useEffect(() => {
    const refresh = () => setRevision(current => current + 1);
    window.addEventListener("milon:data-refresh", refresh);
    return () => window.removeEventListener("milon:data-refresh", refresh);
  }, []);
  const metric = data?.metrics.find(item => item.key === selected) ?? data?.metrics[0];
  return <section className={styles.section} aria-label="Laufstil im Verlauf">
    <header className={styles.header}><div><h2>Laufstil · früh und spät</h2><p>Was sich bei ähnlichem Tempo verändert</p></div><span className={styles.badge}>Garmin · Laufdynamik</span></header>
    {error ? <p className={styles.empty} role="alert">{error} <button onClick={() => setRevision(current => current + 1)}>Erneut laden</button></p> : !data || !metric ? <p className={styles.empty} role="status">Laufstil wird ausgewertet …</p> : <>
      <div className={styles.toolbar}><label htmlFor={selectId} className="sr-only">Kennzahl</label><select id={selectId} value={metric.key} onChange={event => setSelected(event.target.value)}>{data.metrics.map(item => <option key={item.key} value={item.key}>{item.label} · {item.unit}</option>)}</select><span>{metric.pairs} passende Minutenpaare</span></div>
      <div className={styles.values}><div><span>Früh</span><strong>{value(metric.early, metric.unit)}<small>{metric.unit}</small></strong></div><div><span>Spät</span><strong>{value(metric.late, metric.unit)}<small>{metric.unit}</small></strong></div><div><span>Veränderung</span><strong className={styles.delta}>{change(metric.delta, metric.unit)}<small>{metric.unit === "%" ? "%-Pkt." : metric.unit}</small></strong></div></div>
      <MechanicsChart metric={metric} midpoint={data.midpoint_minute} />
      <p className={styles.note}>{metric.definition}</p>
      {metric.status === "observed" ? <p className={styles.note}>Unterschiede der Paare: {change(metric.delta_min, metric.unit)} bis {change(metric.delta_max, metric.unit)} {metric.unit === "%" ? "Prozentpunkte" : metric.unit}. Tempoabweichung im Mittel {change(metric.pace_delta_seconds, "ms")} s/km. Verlauf: alle geeigneten Minuten.</p> : <p className={styles.note}>{data.status === "excluded" ? data.reason : "Für einen Vergleich brauchen wir sechs passende Minutenpaare mit dieser Kennzahl. Fehlende Werte bleiben offen."}</p>}
      <details className={styles.method}><summary>So vergleichen wir</summary><p>{data.method}</p><p>SSL% ist der prozentuale Geschwindigkeitsverlust pro Schritt. Die Rohdaten belegen nicht für jede Kennzahl das genaue Sensormodell. Keine absolute SSL-Einheit aus uneindeutigen Garmin-Metadaten abgeleitet.</p></details>
    </>}
  </section>;
}
