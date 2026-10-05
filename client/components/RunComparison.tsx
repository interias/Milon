"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import Link from "next/link";
import { de, de0 } from "@/lib/format";
import { finite, paceLabel } from "@/lib/garmin";
import { routeDate } from "@/lib/run-routes";
import { runInsightsApi, type RunCohortComparison, type RunDistribution } from "@/lib/run-insights";
import styles from "./RunComparison.module.css";

type Metric = "pace_seconds" | "avg_hr";
const dateLabel = (value: string) => routeDate(value.slice(0, 10));
const metricLabel = (value: number | null, metric: Metric) => metric === "pace_seconds" ? paceLabel(value) : de(value, 1);

function differenceLabel(value: number | null, metric: Metric) {
  if (!finite(value)) return "–";
  const rounded = metric === "pace_seconds" ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded > 0 ? "+" : rounded < 0 ? "−" : ""}${de(Math.abs(rounded), metric === "pace_seconds" ? 0 : 1)}`;
}

type Selection = { activeId: string; onSelect: (id: string) => void };

function DistributionPlot({ data, metric, distribution, activeId, onSelect }: { data: RunCohortComparison; metric: Metric; distribution: RunDistribution } & Selection) {
  const ref = useRef<HTMLDivElement>(null), titleId = useId();
  const [width, setWidth] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  const points = data.cohort.filter(run => finite(run[metric]));
  const values = [...points.map(run => run[metric] as number), distribution.selected].filter(finite);
  if (!values.length) return <p className={styles.note}>Für diese Kennzahl fehlen Messwerte.</p>;
  const minimum = Math.min(...values), maximum = Math.max(...values);
  const padding = Math.max((maximum - minimum) * .12, metric === "pace_seconds" ? 5 : 2);
  const low = minimum - padding, high = maximum + padding;
  const x = (value: number) => 16 + (value - low) / (high - low) * (width - 32);
  const pointLanes = new Map<number, number[]>();
  const dots = points.map(run => {
    const position = x(run[metric] as number);
    const bucket = Math.round(position / 11);
    const neighbours = [bucket - 1, bucket, bucket + 1].flatMap(key => pointLanes.get(key) || []);
    const lane = [0, -1, 1, -2, 2].find(candidate => !neighbours.includes(candidate)) ?? 0;
    pointLanes.set(bucket, [...(pointLanes.get(bucket) || []), lane]);
    return { run, position, lane };
  });
  const unit = metric === "pace_seconds" ? "min/km" : "bpm";
  const ordered = [...data.cohort, data.selected].filter(run => finite(run[metric]))
    .sort((a, b) => (a[metric] as number) - (b[metric] as number) || a.started_at.localeCompare(b.started_at) || a.activity_id.localeCompare(b.activity_id));
  function move(event: KeyboardEvent<SVGGElement>, id: string) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End", "Enter", " "].includes(event.key)) return;
    event.preventDefault();
    const current = ordered.findIndex(run => run.activity_id === id);
    const next = event.key === "Home" ? 0 : event.key === "End" ? ordered.length - 1 : event.key === "ArrowLeft" ? Math.max(0, current - 1) : event.key === "ArrowRight" ? Math.min(ordered.length - 1, current + 1) : current;
    const target = ordered[next];
    if (target) {
      onSelect(target.activity_id);
      ref.current?.querySelector<SVGGElement>(`[data-run-id="${target.activity_id}"]`)?.focus();
    }
  }
  return <div ref={ref} className={styles.chart}>
    <svg viewBox={`0 0 ${width} 76`} aria-labelledby={titleId}>
      <title id={titleId}>{metric === "pace_seconds" ? "Tempo" : "Durchschnittspuls"}: dieser Lauf {metricLabel(distribution.selected, metric)} {unit}; Median der {distribution.n} Vergleichsläufe {metricLabel(distribution.median, metric)} {unit}. Jeder Kreis ist ein anderer Lauf. Die Raute markiert diesen Lauf.</title>
      <line x1="16" x2={width - 16} y1="38" y2="38" className={styles.axis} />
      {distribution.n > 1 && finite(distribution.min) && finite(distribution.max) && <g className={styles.range}>
        <line x1={x(distribution.min)} x2={x(distribution.max)} y1="38" y2="38" />
        <line x1={x(distribution.min)} x2={x(distribution.min)} y1="33" y2="43" />
        <line x1={x(distribution.max)} x2={x(distribution.max)} y1="33" y2="43" />
      </g>}
      {distribution.n >= 5 && finite(distribution.q1) && finite(distribution.q3) && <rect x={x(distribution.q1)} y="28" width={Math.max(1, x(distribution.q3) - x(distribution.q1))} height="20" rx="2" className={styles.quartiles}><title>Mittlere 50 %: {metricLabel(distribution.q1, metric)}–{metricLabel(distribution.q3, metric)} {unit}</title></rect>}
      {finite(distribution.median) && <line x1={x(distribution.median)} x2={x(distribution.median)} y1="23" y2="53" className={styles.median}><title>Median: {metricLabel(distribution.median, metric)} {unit}</title></line>}
      {dots.map(({ run, position, lane }) => <g key={run.activity_id} data-run-id={run.activity_id} role="button" tabIndex={activeId === run.activity_id || !ordered.some(item => item.activity_id === activeId) && ordered[0]?.activity_id === run.activity_id ? 0 : -1} aria-pressed={activeId === run.activity_id} aria-label={`Lauf vom ${dateLabel(run.started_at)} hervorheben: ${metricLabel(run[metric], metric)} ${unit}; ${de(run.overlap_pct, 1)} % Streckenüberdeckung.`} className={`${styles.runPoint} ${activeId === run.activity_id ? styles.activePoint : ""}`} onPointerEnter={event => { if (event.pointerType === "mouse") onSelect(run.activity_id); }} onFocus={() => onSelect(run.activity_id)} onClick={() => onSelect(run.activity_id)} onKeyDown={event => move(event, run.activity_id)}>
        <title>{routeDate(run.started_at)} · {metricLabel(run[metric], metric)} {unit} · {de(run.overlap_pct, 1)} % Überdeckung innerhalb {de0(data.tolerance_m)} m</title>
        <circle cx={position} cy={38 + lane * 7} r="12" fill="transparent" />
        {activeId === run.activity_id && <circle cx={position} cy={38 + lane * 7} r="8" className={styles.halo} />}
        <circle cx={position} cy={38 + lane * 7} r="3.5" className={styles.dot} />
      </g>)}
      {finite(distribution.selected) && <g className={`${styles.selected} ${styles.runPoint}`} data-run-id={data.activity_id} role="button" tabIndex={activeId === data.activity_id || !ordered.some(item => item.activity_id === activeId) && ordered[0]?.activity_id === data.activity_id ? 0 : -1} aria-pressed={activeId === data.activity_id} aria-label="Diesen Lauf in beiden Diagrammen hervorheben" onFocus={() => onSelect(data.activity_id)} onPointerEnter={event => { if (event.pointerType === "mouse") onSelect(data.activity_id); }} onClick={() => onSelect(data.activity_id)} onKeyDown={event => move(event, data.activity_id)}>
        <rect x={x(distribution.selected) - 12} y="0" width="24" height="55" fill="transparent" />
        {activeId === data.activity_id && <circle cx={x(distribution.selected)} cy="11" r="10" className={styles.halo} />}
        <line x1={x(distribution.selected)} x2={x(distribution.selected)} y1="16" y2="50" />
        <path d={`M${x(distribution.selected)},5 l6,6 -6,6 -6,-6 Z`} />
        <title>Dieser Lauf: {metricLabel(distribution.selected, metric)} {unit}</title>
      </g>}
      {[minimum, ...(minimum !== maximum ? [maximum] : [])].map((value, index, ticks) => <text key={value} x={x(value)} y="71" textAnchor={ticks.length === 1 ? "middle" : index === 0 ? "start" : "end"}>{metricLabel(value, metric)}</text>)}
    </svg>
  </div>;
}

function DistributionRow({ data, metric, activeId, onSelect }: { data: RunCohortComparison; metric: Metric } & Selection) {
  const distribution = data.metrics[metric];
  return <div className={styles.metric}>
    <div className={styles.metricHeader}>
      <h3>{metric === "pace_seconds" ? "Tempo" : "Ø Puls"}<span>{metric === "pace_seconds" ? "min/km" : "bpm"}</span></h3>
      <dl className={styles.values}>
        <div><dt>Dieser Lauf</dt><dd className={styles.currentValue}>{metricLabel(distribution.selected, metric)}</dd></div>
        <div><dt>Median{distribution.n !== data.cohort.length ? ` · ${distribution.n}` : ""}</dt><dd>{metricLabel(distribution.median, metric)}</dd></div>
        <div><dt>Abstand <span>{metric === "pace_seconds" ? "s/km" : "bpm"}</span></dt><dd>{differenceLabel(distribution.delta, metric)}</dd></div>
      </dl>
    </div>
    <DistributionPlot data={data} metric={metric} distribution={distribution} activeId={activeId} onSelect={onSelect} />
  </div>;
}

export function RunComparison({ activityId }: { activityId: string }) {
  const headingId = useId();
  const [data, setData] = useState<RunCohortComparison | null>(null), [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [selectedId, setSelectedId] = useState(activityId);
  useEffect(() => setSelectedId(activityId), [activityId]);
  useEffect(() => {
    const refresh = () => setRevision(value => value + 1);
    const events = ["milon:data-refresh", "run-analysis-updated"];
    events.forEach(event => window.addEventListener(event, refresh));
    return () => events.forEach(event => window.removeEventListener(event, refresh));
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError("");
    runInsightsApi.cohort(activityId, controller.signal).then(value => { if (!controller.signal.aborted) setData(value); }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Vergleich konnte nicht geladen werden."); });
    return () => controller.abort();
  }, [activityId, revision]);
  const current = data?.activity_id === activityId ? data : null;
  const active = current?.cohort.find(run => run.activity_id === selectedId) || current?.selected;
  return <section className={styles.section} aria-labelledby={headingId}>
    <header className={styles.header}>
      <div><h2 id={headingId}>Läufe vergleichen</h2><p>Alle anderen passenden Läufe auf dieser Strecke</p></div>
      {current && <span className={styles.threshold}>≥ {de0(current.threshold_pct)} % Überdeckung · {de0(current.tolerance_m)} m GPS-Toleranz</span>}
    </header>
    {error ? <p className={styles.note} role="alert">{error} <button type="button" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></p> : !current ? <p className={styles.note} role="status">Passende Strecken werden verglichen …</p> : <>
      {current.status === "ready" ? <>
        <p className={styles.scope}><strong>{de0(current.cohort.length)} {current.cohort.length === 1 ? "Vergleichslauf" : "Vergleichsläufe"}</strong>{current.period_start && current.period_end && <span>{dateLabel(current.period_start)}{current.period_start.slice(0, 10) !== current.period_end.slice(0, 10) ? `–${dateLabel(current.period_end)}` : ""}</span>}<span>{current.sensor_label}</span></p>
        <div className={styles.legend} aria-hidden="true"><span><i className={styles.selectedKey} />Dieser Lauf</span><span><i className={styles.dotKey} />Andere Läufe</span><span><i className={styles.medianKey} />Median</span>{Math.max(current.metrics.pace_seconds.n, current.metrics.avg_hr.n) >= 5 && <span><i className={styles.quartileKey} />Mittlere 50 %</span>}</div>
        {active && <div className={styles.readout}>
          <span className={styles.readoutDate}>{active.activity_id === activityId ? "Dieser Lauf" : dateLabel(active.started_at)}</span>
          <span><strong>{paceLabel(active.pace_seconds)}</strong> min/km</span><span><strong>{de0(active.avg_hr)}</strong> bpm</span>
          {active.activity_id !== activityId ? <Link href={`/laufen/${active.activity_id}#vergleich`}>Lauf öffnen ↗</Link> : <span className={styles.readoutHint}>Punkt antippen</span>}
        </div>}
        <DistributionRow data={current} metric="pace_seconds" activeId={active?.activity_id || activityId} onSelect={setSelectedId} />
        <DistributionRow data={current} metric="avg_hr" activeId={active?.activity_id || activityId} onSelect={setSelectedId} />
        {current.cohort.length < 5 && <p className={styles.note}>{current.cohort.length === 1 ? "Erst ein Vergleichslauf: noch keine Streuung ablesbar." : "Noch wenige Wiederholungen: Einzelwerte und gesamte Spanne, kein Quartilband."}</p>}
        <p className={styles.note}>Abstand = dieser Lauf minus Median. Tempo und Puls gemeinsam lesen; Wetter und Trainingsziel wirken mit.</p>
      </> : <p className={styles.empty}>{current.reason || "Noch kein anderer Lauf erfüllt die Streckenübereinstimmung."}</p>}
      <details className={styles.method}><summary>So wird verglichen</summary><p>{current.method}</p><p>{de0(current.tolerance_m)} m GPS-Toleranz · {current.sensor_label}{current.sensor_since ? ` seit ${dateLabel(current.sensor_since)}` : ""}. Alle gespeicherten passenden Läufe, auch nach dem ausgewählten Datum; dieser Lauf selbst bleibt aus der Verteilung ausgeschlossen.</p></details>
    </>}
  </section>;
}
