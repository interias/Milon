"use client";

import { useEffect, useId, useRef, useState, type PointerEvent } from "react";
import { Card } from "@/components/ui";
import { garminNightsApi, nightClock, nightValue, nightWallHour, type GarminNight, type GarminNightList, type NightMetric, type NightStage } from "@/lib/garmin-nights";
import styles from "./GarminNights.module.css";

const STAGES: Record<NightStage, { label: string; color: string; row: number }> = {
  awake: { label: "Wach", color: "#b77b20", row: 0 },
  rem: { label: "REM", color: "#8a78a5", row: 1 },
  light: { label: "Leicht", color: "#6fb9ae", row: 2 },
  deep: { label: "Tief", color: "#0a6e66", row: 3 },
  unknown: { label: "Unbekannt", color: "#aab5b3", row: 4 },
};
const METRICS: Record<NightMetric, { label: string; unit: string; color: string }> = {
  heart_rate: { label: "Puls", unit: "bpm", color: "#0a6e66" },
  body_battery: { label: "Body Battery", unit: "/ 100", color: "#8a78a5" },
  stress: { label: "Stress", unit: "/ 100", color: "#b77b20" },
  hrv: { label: "HRV", unit: "ms", color: "#437d9b" },
};
const labelDate = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString("de-DE", { timeZone: "UTC", day: "2-digit", month: "2-digit" });
const duration = (minutes: number | null) => minutes === null ? "—" : `${Math.floor(Math.round(minutes) / 60)} h ${String(Math.round(minutes) % 60).padStart(2, "0")}`;
const number = (value: number) => Math.round(value).toLocaleString("de-DE");

function NightPlot({ night }: { night: GarminNight }) {
  const host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [cursor, setCursor] = useState<number | null>(null);
  const available = (Object.keys(METRICS) as NightMetric[]).filter(key => night.series[key].samples > 0);
  const [chosen, setChosen] = useState<NightMetric[]>(() => available.slice(0, 2));
  const selected = chosen.filter(key => available.includes(key)).slice(0, 2);
  const id = useId();
  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(180, entry.contentRect.width)));
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  const left = 40, right = width - 9, durationSeconds = night.window_minutes * 60;
  const x = (seconds: number) => left + seconds / durationSeconds * (right - left);
  const clock = (seconds: number) => nightClock(new Date(Date.parse(night.started_at_utc) + seconds * 1000).toISOString(), night.timezone);
  const height = 88 + selected.length * 64;
  const activePhase = cursor === null ? null : night.phases.find(phase => phase.start_seconds <= cursor && cursor < phase.end_seconds);
  function pick(event: PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = (event.clientX - rect.left) / rect.width * width;
    setCursor(Math.max(0, Math.min(durationSeconds, (px - left) / (right - left) * durationSeconds)));
  }
  return <div ref={host} className={styles.plotHost}>
    <div className={styles.seriesControls}><span>Verlauf</span>{[0, 1].filter(index => index < available.length).map(index => <select key={index} aria-label={`Messreihe ${index + 1}`} value={selected[index] ?? ""}
      onChange={event => setChosen(previous => { const next = [...previous]; next[index] = event.target.value as NightMetric; return next; })}>
      {available.filter(key => selected[1 - index] !== key).map(key => <option key={key} value={key}>{METRICS[key].label}</option>)}
    </select>)}</div>
    <svg viewBox={`0 0 ${width} ${height}`} height={height} className={styles.plot} role="group" tabIndex={0}
      aria-label="Nachtverlauf. Berühren oder mit den Pfeiltasten durch Schlafphasen und Messwerte gehen."
      onPointerMove={pick} onPointerDown={event => { event.currentTarget.focus(); pick(event); }}
      onKeyDown={event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
        event.preventDefault();
        if (event.key === "Escape") setCursor(null);
        else if (event.key === "Home") setCursor(0);
        else if (event.key === "End") setCursor(durationSeconds);
        else setCursor(previous => Math.max(0, Math.min(durationSeconds, (previous ?? durationSeconds / 2) + (event.key === "ArrowRight" ? 600 : -600))));
      }}>
      <defs><pattern id={`${id}-unknown`} patternUnits="userSpaceOnUse" width="5" height="5"><path d="M0 5L5 0" stroke="#d2dad8" strokeWidth="1" /></pattern></defs>
      <rect x={left} y="7" width={right - left} height="52" fill={`url(#${id}-unknown)`} opacity=".55" />
      {(["awake", "rem", "light", "deep"] as NightStage[]).map(stage => <g key={stage}>
        <text x={left - 7} y={16 + STAGES[stage].row * 13} textAnchor="end">{STAGES[stage].label}</text>
        <line x1={left} x2={right} y1={19 + STAGES[stage].row * 13} y2={19 + STAGES[stage].row * 13} stroke="var(--color-line)" />
      </g>)}
      {night.phases.map((phase, index) => <g key={index}>
        <rect x={x(phase.start_seconds)} y="7" width={Math.max(0, x(phase.end_seconds) - x(phase.start_seconds))} height="52" fill="white" />
        {phase.stage !== "unknown" && <rect x={x(phase.start_seconds)} y={8 + STAGES[phase.stage].row * 13} width={Math.max(.7, x(phase.end_seconds) - x(phase.start_seconds))} height="10" rx="1" fill={STAGES[phase.stage].color} />}
        {phase.stage === "unknown" && <rect x={x(phase.start_seconds)} y="7" width={x(phase.end_seconds) - x(phase.start_seconds)} height="52" fill={`url(#${id}-unknown)`} />}
      </g>)}
      {!night.phases.length && <text x={(left + right) / 2} y="37" textAnchor="middle">{night.stage_conflict ? "Phasen widersprüchlich" : "Keine Phasen verfügbar"}</text>}
      {selected.map((key, index) => {
        const series = night.series[key], metric = METRICS[key];
        const low = Math.floor((series.minimum ?? 0) / 5) * 5;
        const high = Math.max(low + 10, Math.ceil((series.maximum ?? 0) / 5) * 5);
        const top = 90 + index * 64, bottom = top + 33;
        const y = (value: number) => bottom - (value - low) / (high - low) * (bottom - top);
        const active = cursor === null ? null : nightValue(series, cursor);
        return <g key={key}>
          <text x={left} y={top - 9} className={styles.metricTitle}>{metric.label} <tspan className={styles.metricUnit}>· {metric.unit}</tspan></text>
          <text x={right} y={top - 9} textAnchor="end" fill={metric.color}>{cursor !== null ? active === null ? "Lücke" : `${number(active)} ${metric.unit}` : ""}</text>
          {[low, high].map(value => <g key={value}><text x={left - 7} y={y(value) + 3} textAnchor="end">{number(value)}</text><line x1={left} x2={right} y1={y(value)} y2={y(value)} stroke="var(--color-line)" /></g>)}
          {series.segments.map((segment, segmentIndex) => segment.length === 1 ? <circle key={segmentIndex} cx={x(segment[0].seconds)} cy={y(segment[0].value)} r="1.8" fill={metric.color} /> : <path key={segmentIndex} d={segment.map((point, pointIndex) => `${pointIndex ? "L" : "M"}${x(point.seconds).toFixed(1)},${y(point.value).toFixed(1)}`).join(" ")} stroke={metric.color} strokeWidth="1.6" fill="none" />)}
        </g>;
      })}
      {[0, .5, 1].map(fraction => <text key={fraction} x={x(durationSeconds * fraction)} y={height - 3} textAnchor={fraction === 0 ? "start" : fraction === 1 ? "end" : "middle"}>{clock(durationSeconds * fraction)}</text>)}
      {cursor !== null && <line x1={x(cursor)} x2={x(cursor)} y1="5" y2={height - 19} stroke="var(--color-muted)" strokeDasharray="3 3" />}
    </svg>
    <p className={styles.readout} role="status" aria-live="polite">{cursor === null ? "Berühren oder ← → · Schraffur: Phase unbekannt" : `${clock(cursor)} Uhr · ${activePhase ? STAGES[activePhase.stage].label : "Phase unbekannt"}`}</p>
    {!available.length && <p className={styles.note}>Für diese Nacht wurden keine zeitaufgelösten Messreihen geliefert.</p>}
  </div>;
}

function Rhythm({ data, selected, onSelect }: { data: GarminNightList; selected: string; onSelect: (day: string) => void }) {
  const dates: string[] = [];
  for (let stamp = Date.parse(`${data.from_date}T12:00:00Z`); stamp <= Date.parse(`${data.to_date}T12:00:00Z`); stamp += 86_400_000) dates.push(new Date(stamp).toISOString().slice(0, 10));
  const bounds = data.nights.flatMap(night => [nightWallHour(night.started_at, night.day), nightWallHour(night.ended_at, night.day)]);
  const low = Math.min(-4, Math.floor(Math.min(...bounds, -4) / 2) * 2);
  const high = Math.max(10, Math.ceil(Math.max(...bounds, 10) / 2) * 2);
  const position = (hour: number) => (hour - low) / (high - low) * 100;
  const tick = (hour: number) => `${String((hour + 48) % 24).padStart(2, "0")}`;
  return <div className={styles.rhythm}>
    <div className={styles.rhythmTitle}><h3>Dein Schlafrhythmus</h3><span>Aufwachtag</span></div>
    <div className={styles.rhythmAxis}><span>{tick(low)} Uhr</span><span className={styles.midnightLabel} style={{ left: `${position(0)}%` }}>00</span><span>{tick(high)} Uhr</span></div>
    <div className={styles.nights}>{dates.map(day => {
      const night = data.nights.find(item => item.day === day);
      if (!night) return <div key={day} className={`${styles.nightRow} ${styles.noNight}`}><span>{labelDate(day)}</span><span className={styles.track}>nicht erfasst</span></div>;
      const start = position(nightWallHour(night.started_at, day)), end = position(nightWallHour(night.ended_at, day));
      const title = `${labelDate(day)} · ${nightClock(night.started_at, data.timezone)}–${nightClock(night.ended_at, data.timezone)} Uhr${night.complete ? ` · ${duration(night.asleep_minutes)} Schlaf` : " · Phasen unvollständig"}${night.clock_change ? " · Zeitumstellung" : ""}`;
      return <button type="button" key={day} title={title} aria-label={title} aria-pressed={day === selected}
        className={`${styles.nightRow} ${day === selected ? styles.activeNight : ""}`} onClick={() => onSelect(day)}>
        <span>{labelDate(day)}</span><span className={styles.track}><span className={`${styles.sleepBar} ${!night.complete ? styles.partialBar : ""}`} style={{ left: `${start}%`, width: `${Math.max(.6, end - start)}%` }} />
          <span className={styles.midnight} style={{ left: `${position(0)}%` }} /></span>
      </button>;
    })}</div>
    <p className={styles.note}>Eine Zeile = ein Schlaffenster. Antippen für die Nacht.</p>
  </div>;
}

export function GarminNights() {
  const [days, setDays] = useState<14 | 30>(14), [revision, setRevision] = useState(0);
  const [data, setData] = useState<GarminNightList | null>(null), [selected, setSelected] = useState("");
  const [night, setNight] = useState<GarminNight | null>(null);
  const [error, setError] = useState(""), [nightError, setNightError] = useState("");
  useEffect(() => {
    const refresh = () => setRevision(value => value + 1);
    window.addEventListener("milon:data-refresh", refresh);
    return () => window.removeEventListener("milon:data-refresh", refresh);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setData(null);
    garminNightsApi.list(days, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      setData(value);
      setSelected(previous => value.nights.some(item => item.day === previous) ? previous : value.nights.at(-1)?.day ?? "");
    }).catch(() => { if (!controller.signal.aborted) setError("Die Nächte konnten nicht geladen werden."); });
    return () => controller.abort();
  }, [days, revision]);
  useEffect(() => {
    const controller = new AbortController();
    setNight(null); setNightError("");
    if (selected) garminNightsApi.night(selected, controller.signal).then(value => { if (!controller.signal.aborted) setNight(value); })
      .catch(() => { if (!controller.signal.aborted) setNightError("Diese Nacht konnte nicht geladen werden."); });
    return () => controller.abort();
  }, [selected, revision]);
  return <Card className={`mt-4 ${styles.card}`}>
    <div className={styles.header}><div><h2>Deine Nacht</h2><p>Schlafphasen, Messverläufe & Rhythmus · Garmin direkt</p></div>
      <div className={styles.period} aria-label="Zeitraum">{([14, 30] as const).map(value => <button type="button" key={value} aria-pressed={days === value} onClick={() => setDays(value)}>{value} Tage</button>)}</div>
    </div>
    {error && <p className={styles.error} role="alert">{error} <button type="button" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></p>}
    {!data && !error && <p className={styles.empty} role="status">Nächte werden geladen …</p>}
    {data && !data.nights.length && <p className={styles.empty}>In diesen {days} Tagen ist noch keine Garmin-Hauptschlafphase verfügbar.</p>}
    {data && data.nights.length > 0 && <div className={styles.content}>
      <div className={styles.detail}>
        {nightError ? <p className={styles.error} role="alert">{nightError} <button type="button" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></p> : !night ? <p className={styles.empty} role="status">Nacht wird geladen …</p> : <>
          <div className={styles.nightHeading}><h3>Nacht zum {labelDate(night.day)}</h3><span>{nightClock(night.started_at, night.timezone)}–{nightClock(night.ended_at, night.timezone)} Uhr</span></div>
          <div className={styles.summary}>
            <div><span>Schlaf</span><strong>{duration(night.asleep_minutes)}</strong></div>
            <div><span>Wach</span><strong>{night.awake_minutes === null ? "—" : `${number(night.awake_minutes)} min`}</strong></div>
            <div><span>Body Battery Δ</span><strong>{night.battery_change === null ? "—" : `${night.battery_change > 0 ? "+" : ""}${number(night.battery_change)}`}<small>{night.battery_change !== null ? " Pkt." : ""}</small></strong></div>
          </div>
          {!night.complete && <p className={styles.note}>Phasen unvollständig · Schlafdauer bleibt offen.</p>}
          {night.clock_change && <p className={styles.note}>Zeitumstellung: Die Kurven zeigen tatsächlich vergangene Zeit.</p>}
          <NightPlot key={night.day + (night.synced_at ?? "")} night={night} />
          <p className={styles.note}>Schlafphasen, Stress und Body Battery sind Garmin-Schätzungen. Lücken bleiben sichtbar.{night.sync_issue ? " Letzter Abruf fehlgeschlagen; letzter verfügbarer Stand." : ""}</p>
        </>}
      </div>
      <Rhythm data={data} selected={selected} onSelect={setSelected} />
    </div>}
  </Card>;
}
