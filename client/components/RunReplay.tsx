"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { finite, nearestActivityPoint, paceLabel, paceSeconds, type GarminActivityPoint } from "@/lib/garmin";
import { projectRunRoute, type RunRouteDetail } from "@/lib/run-routes";
import { routePosition, timedRoute } from "@/lib/run-insights";
import { de, de0, dur } from "@/lib/format";
import styles from "./RunReplay.module.css";

export function RunReplay({ route, points, startedAtUtc }: { route: RunRouteDetail; points: GarminActivityPoint[]; startedAtUtc: string | null | undefined }) {
  const [elapsed, setElapsed] = useState(0), [playing, setPlaying] = useState(false), [reduced, setReduced] = useState(false);
  const [rate, setRate] = useState(120), [open, setOpen] = useState(false);
  const label = useId();
  const geometry = useMemo(() => projectRunRoute(route.segments, 480, 210, 20), [route]);
  const timeline = useMemo(() => geometry ? timedRoute(route.segments, geometry.segments, startedAtUtc) : [], [route, geometry, startedAtUtc]);
  const series = useMemo(() => points.filter(point => finite(point.elapsed_seconds)).sort((a, b) => a.elapsed_seconds - b.elapsed_seconds), [points]);
  const end = Math.max(0, timeline.at(-1)?.at(-1)?.elapsed ?? 0, series.at(-1)?.elapsed_seconds ?? 0);
  useEffect(() => {
    const preference = matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => { setReduced(preference.matches); if (preference.matches) setPlaying(false); };
    update(); preference.addEventListener("change", update);
    const pause = () => { if (document.hidden) setPlaying(false); };
    document.addEventListener("visibilitychange", pause);
    return () => { preference.removeEventListener("change", update); document.removeEventListener("visibilitychange", pause); };
  }, []);
  useEffect(() => {
    if (!playing || reduced || !open) return;
    let last = performance.now();
    const timer = setInterval(() => {
      const now = performance.now(), delta = Math.min(1, (now - last) / 1000) * rate;
      last = now;
      setElapsed(value => Math.min(end, value + delta));
    }, 100);
    return () => clearInterval(timer);
  }, [playing, reduced, open, rate, end]);
  useEffect(() => { if (elapsed >= end) setPlaying(false); }, [elapsed, end]);
  if (!geometry?.hasExtent || !timeline.length || end <= 0) return null;
  const position = routePosition(timeline, elapsed);
  const nearestIndex = nearestActivityPoint(series, elapsed);
  const nearest = nearestIndex == null ? null : series[nearestIndex];
  const active = nearest && Math.abs(nearest.elapsed_seconds - elapsed) <= 15 && !nearest.gap ? nearest : null;
  const progress = timeline.map(segment => segment.filter(point => point.elapsed <= elapsed));
  return <details className={styles.replay} onToggle={event => { setOpen(event.currentTarget.open); if (!event.currentTarget.open) setPlaying(false); }}>
    <summary>Lauf wiedergeben <span>Strecke · Puls · Tempo</span></summary>
    <div className={styles.content}>
      <svg viewBox="0 0 480 210" role="img" aria-labelledby={label}>
        <title id={label}>Wiedergabe der GPS-Strecke, Norden oben. Lücken werden nicht überbrückt.</title>
        {geometry.segments.map((segment, index) => <path key={`base-${index}`} d={segment.map((point, i) => `${i ? "L" : "M"}${point.x},${point.y}`).join(" ")} fill="none" stroke="#d1e1dc" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />)}
        {progress.map((segment, index) => <path key={`progress-${index}`} d={segment.map((point, i) => `${i ? "L" : "M"}${point.x},${point.y}`).join(" ")} fill="none" stroke="#0a6e66" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />)}
        <circle cx={geometry.start.x} cy={geometry.start.y} r="3.5" fill="#0a6e66" stroke="white" />
        <circle cx={geometry.end.x} cy={geometry.end.y} r="5" stroke="#14201f" strokeWidth="1.5" fill="none" />
        {position && <circle cx={position.x} cy={position.y} r="6" fill="#9a5b00" stroke="white" strokeWidth="2" />}
        <text x="463" y="19" textAnchor="middle" fill="#4d5b5a" fontSize="10">N</text>
      </svg>
      <div className={styles.readout}><strong>{dur(elapsed)}</strong><span>{active ? de0(active.hr_bpm) : "–"} <small>bpm</small></span><span>{active ? active.speed_m_s === 0 ? "Stillstand" : `${paceLabel(paceSeconds(active.speed_m_s))} /km` : "– /km"}</span><span>{active ? de(active.distance_m == null ? null : active.distance_m / 1000, 2) : "–"} <small>km</small></span></div>
      <label className={styles.slider}><span className="sr-only">Zeitpunkt der Wiedergabe</span><input type="range" min="0" max={end} step="1" value={elapsed} aria-valuetext={dur(elapsed)} onChange={event => { setPlaying(false); setElapsed(Number(event.target.value)); }} /></label>
      <div className={styles.controls}><button type="button" disabled={reduced} onClick={() => { if (elapsed >= end) setElapsed(0); setPlaying(value => !value); }}>{playing ? "Pause" : elapsed >= end ? "Erneut abspielen" : "Abspielen"}</button><button type="button" onClick={() => { setPlaying(false); setElapsed(0); }}>Zum Start</button><label><span className="sr-only">Wiedergabegeschwindigkeit</span><select value={rate} onChange={event => setRate(Number(event.target.value))}><option value="60">60×</option><option value="120">120×</option><option value="240">240×</option></select></label></div>
      <p className={styles.note}>{reduced ? "Reduzierte Bewegung ist aktiv. Nutze den Zeitregler zum Erkunden." : !position ? "An diesem Zeitpunkt fehlen GPS-Punkte. Die Wiedergabe überspringt keine Zeitlücken." : "Messwerte am nächsten aufgezeichneten Zeitpunkt · keine Ergänzung fehlender Sensorwerte."}</p>
    </div>
  </details>;
}
