"use client";

import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { Card } from "@/components/ui";
import { finite, garminApi, type GarminRecovery as RecoveryData, type GarminRecoveryMetric, type GarminRecoveryPoint } from "@/lib/garmin";
import { de, de0 } from "@/lib/format";
import styles from "./GarminRecovery.module.css";

const dateLabel = (date: string) => new Date(`${date.slice(0, 10)}T12:00:00`).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
const dateTime = (date: string) => new Date(date).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const time = (date: string) => new Date(`${date.slice(0, 10)}T12:00:00Z`).getTime();
const consecutive = (a: GarminRecoveryPoint, b: GarminRecoveryPoint) => time(b.date) - time(a.date) <= 86400000;

function metricDate(metric: GarminRecoveryMetric | null, snapshot = false) {
  if (!metric) return "Noch nicht verfügbar";
  return `${metric.measured_at ? dateTime(metric.measured_at) : dateLabel(metric.date)}${metric.provisional ? snapshot ? " · letzter Stand" : " · vorläufig" : ""}${metric.stale ? " · älterer Wert" : ""}`;
}

function RecoveryTrend({ series, kind }: { series: GarminRecoveryPoint[]; kind: "hrv_ms" | "rhr_bpm" }) {
  const host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600), [selected, setSelected] = useState<number | null>(null);
  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(160, entry.contentRect.width)));
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  const points = useMemo(() => [...series].sort((a, b) => a.date.localeCompare(b.date)), [series]);
  const values = points.map(point => point[kind]).filter(finite);
  const hasBaseline = (point: GarminRecoveryPoint) => kind === "hrv_ms" && point.hrv_status != null && point.hrv_status !== "NONE" && finite(point.baseline_low_ms) && finite(point.baseline_high_ms) && point.baseline_low_ms <= point.baseline_high_ms;
  const rangeValues = [...values, ...points.flatMap(point => hasBaseline(point) ? [point.baseline_low_ms!, point.baseline_high_ms!] : [])];
  const low = Math.floor((Math.min(...rangeValues, 10000) - 3) / 5) * 5;
  const high = Math.max(low + 10, Math.ceil((Math.max(...rangeValues, 0) + 3) / 5) * 5);
  const left = 34, right = width - 10, top = 12, bottom = 100;
  const first = points[0] ? time(points[0].date) : 0, last = points.at(-1) ? time(points.at(-1)!.date) : 1;
  const x = (point: GarminRecoveryPoint) => first === last ? (left + right) / 2 : left + (time(point.date) - first) / (last - first) * (right - left);
  const y = (value: number) => bottom - (value - low) / (high - low) * (bottom - top);
  const active = selected == null ? null : points[Math.min(selected, points.length - 1)];
  const unit = kind === "hrv_ms" ? "ms" : "bpm";
  const hasBand = points.some(hasBaseline);
  function selectPoint(event: PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = (event.clientX - rect.left) / rect.width * width;
    let nearest = 0;
    points.forEach((point, index) => { if (Math.abs(x(point) - px) < Math.abs(x(points[nearest]) - px)) nearest = index; });
    setSelected(nearest);
  }
  return <div ref={host} className={styles.trend}>
    <div className={styles.trendTitle}><h3>{kind === "hrv_ms" ? "HRV · nächtlicher Durchschnitt" : "Garmin-Ruhepuls · Tageswerte"}</h3><span>Bis zu 30 Tage · {unit}</span></div>
    {!values.length ? <p className={styles.empty}>Noch keine {kind === "hrv_ms" ? "HRV-Nächte" : "Garmin-Ruhepulswerte"} verfügbar.</p> : <>
      <svg viewBox={`0 0 ${width} 126`} height="126" className={styles.plot} role="group" tabIndex={0}
        aria-label={`${kind === "hrv_ms" ? "Nächtliche HRV" : "Garmin-Ruhepuls"} in ${unit}. Mit Pfeiltasten Tage auswählen.`}
        onPointerMove={selectPoint} onPointerDown={event => { event.currentTarget.focus(); selectPoint(event); }}
        onKeyDown={event => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
          event.preventDefault(); event.stopPropagation();
          if (event.key === "Escape") { setSelected(null); return; }
          if (event.key === "Home") { setSelected(0); return; }
          if (event.key === "End") { setSelected(points.length - 1); return; }
          setSelected(previous => Math.max(0, Math.min(points.length - 1, previous == null ? event.key === "ArrowRight" ? 0 : points.length - 1 : previous + (event.key === "ArrowRight" ? 1 : -1))));
        }}>
        {[low, (low + high) / 2, high].map(value => <g key={value}><line x1={left} x2={right} y1={y(value)} y2={y(value)} stroke="var(--color-line)" /><text x={left - 8} y={y(value) + 4} textAnchor="end">{de(value, Number.isInteger(value) ? 0 : 1)}</text></g>)}
        {points.map((point, index) => {
          const previous = points[index - 1];
          return <g key={point.date}>
            {hasBaseline(point) && previous && hasBaseline(previous) && consecutive(previous, point) && <polygon points={`${x(previous)},${y(previous.baseline_low_ms!)} ${x(point)},${y(point.baseline_low_ms!)} ${x(point)},${y(point.baseline_high_ms!)} ${x(previous)},${y(previous.baseline_high_ms!)}`} fill="#70817c" opacity=".12" />}
            {finite(point[kind]) && <>
              {previous && finite(previous[kind]) && consecutive(previous, point) && <line x1={x(previous)} x2={x(point)} y1={y(previous[kind]!)} y2={y(point[kind]!)} stroke="var(--color-accent)" strokeWidth="1.8" />}
              <circle cx={x(point)} cy={y(point[kind]!)} r="2.7" fill={point.provisional ? "white" : "var(--color-accent)"} stroke="var(--color-accent)" strokeWidth="1.4" />
            </>}
          </g>;
        })}
        {active && <><line x1={x(active)} x2={x(active)} y1={top} y2={bottom} stroke="var(--color-muted)" strokeDasharray="3 3" />{finite(active[kind]) && <circle cx={x(active)} cy={y(active[kind]!)} r="4.5" fill="white" stroke="var(--color-accent)" strokeWidth="2" />}</>}
        {(first === last ? [.5] : [0, .5, 1]).map(fraction => <text key={fraction} x={left + fraction * (right - left)} y="121" textAnchor={fraction === 0 ? "start" : fraction === 1 ? "end" : "middle"}>{dateLabel(new Date(first + fraction * (last - first)).toISOString())}</text>)}
      </svg>
      <div className={styles.chartReadout} role="status" aria-live="polite">{active ? `${dateLabel(active.date)} · ${de0(active[kind])} ${unit}${active.provisional ? " · vorläufig" : ""}${hasBaseline(active) ? ` · Basisbereich ${de0(active.baseline_low_ms)}–${de0(active.baseline_high_ms)} ms` : ""}` : `Berühren oder mit ← → erkunden${hasBand ? " · graues Band: Garmin-Basisbereich" : ""}`}</div>
    </>}
  </div>;
}

export function GarminRecovery() {
  const [data, setData] = useState<RecoveryData | null>(null), [error, setError] = useState("");
  const [revision, setRevision] = useState(0), [kind, setKind] = useState<"hrv_ms" | "rhr_bpm">("hrv_ms");
  useEffect(() => {
    const refresh = () => setRevision(value => value + 1);
    window.addEventListener("milon:data-refresh", refresh);
    return () => window.removeEventListener("milon:data-refresh", refresh);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    garminApi.recovery(controller.signal).then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Erholungsdaten konnten nicht geladen werden."); });
    return () => controller.abort();
  }, [revision]);
  const latest = data?.latest;
  return <Card className={`mt-4 ${styles.card}`}>
    <div className={styles.header}><div><h2>Erholung · Garmin</h2><p>Messwerte und Einschätzungen deiner Uhr</p></div><span className={styles.direct}>Garmin direkt</span></div>
    {error && <div className={styles.error} role="alert"><span>{error}</span><button type="button" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></div>}
    {!data ? !error && <p className={styles.empty} role="status">Erholungsdaten werden geladen …</p> : <>
      <div className={styles.metrics}>
        <button type="button" aria-pressed={kind === "hrv_ms"} onClick={() => setKind("hrv_ms")} className={kind === "hrv_ms" ? styles.selected : ""}><span>HRV · letzte Messnacht</span><strong>{de0(latest!.hrv_ms?.value)} <small>ms</small></strong><small>{metricDate(latest!.hrv_ms)}</small></button>
        <button type="button" aria-pressed={kind === "rhr_bpm"} onClick={() => setKind("rhr_bpm")} className={kind === "rhr_bpm" ? styles.selected : ""}><span>Garmin-Ruhepuls</span><strong>{de0(latest!.rhr_bpm?.value)} <small>bpm</small></strong><small>{metricDate(latest!.rhr_bpm)}</small></button>
        <div><span>Trainingsbereitschaft</span><strong>{de0(latest!.readiness?.value)} <small>/ 100</small></strong><small>{metricDate(latest!.readiness, true)}</small></div>
        <div><span>Body Battery</span><strong>{de0(latest!.body_battery?.value)} <small>/ 100</small></strong><small>{metricDate(latest!.body_battery, true)}</small></div>
      </div>
      <RecoveryTrend key={kind} series={data.series} kind={kind} />
      <p className={styles.note}>{kind === "hrv_ms" ? latest!.hrv_ms?.baseline_ready ? "Der graue Bereich ist dein persönlicher Garmin-Basisbereich." : "Dein persönlicher HRV-Basisbereich ist noch nicht verfügbar. Wir zeigen den Verlauf ohne Bewertung." : "Garmins eigener Tages-Ruhepuls. Separat vom bisherigen Health-Connect-Wert; die Berechnungen können abweichen."}</p>
      <details className={styles.details}><summary>Einordnung & weitere Werte</summary><div className={styles.secondary}>
        {latest!.recovery_hours && <p>Erholungszeit <strong>{de(latest!.recovery_hours.value, 1)} h</strong><span>{metricDate(latest!.recovery_hours, true)}</span></p>}
        {latest!.stress && <p>Stress · Tagesmittel <strong>{de0(latest!.stress.value)} / 100</strong><span>{metricDate(latest!.stress)}</span></p>}
        {latest!.sleep_score && <p>Schlafscore <strong>{de0(latest!.sleep_score.value)} / 100</strong><span>{metricDate(latest!.sleep_score)}</span></p>}
      </div><p className={styles.note}>Trainingsbereitschaft, Body Battery und Erholungszeit sind Garmin-Schätzungen. Die Trainingsbereitschaft ist der zuletzt abgerufene Stand, kein garantierter Morgenwert. Body Battery zeigt den letzten verfügbaren Tagesstand.</p>
        <p className={styles.note}>{data.coverage.hrv_nights} HRV-Nächte · {data.coverage.resting_hr_days} Tage mit Garmin-Ruhepuls. Fehlende Werte bleiben unbekannt.</p>
        {data.notes.map((note, index) => <p key={index} className={styles.note}>{note}</p>)}
      </details>
      {data.updated_at && <p className={`${styles.synced} ${data.stale ? styles.stale : ""}`}>{data.stale ? "Älterer Datenstand" : "Letzter Abruf"} · {dateTime(data.updated_at)}</p>}
    </>}
  </Card>;
}
