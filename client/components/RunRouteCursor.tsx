"use client";

import { useId, useMemo } from "react";
import { projectRunRoute, type RunRouteDetail } from "@/lib/run-routes";
import { routePosition, timedRoute } from "@/lib/run-insights";
import styles from "./RunActivityDetail.module.css";

export function RunRouteCursor({ route, startedAtUtc, elapsed }: { route: RunRouteDetail; startedAtUtc: string | null | undefined; elapsed: number | null }) {
  const title = useId();
  const geometry = useMemo(() => projectRunRoute(route.segments, 200, 200, 22), [route]);
  const timeline = useMemo(() => geometry ? timedRoute(route.segments, geometry.segments, startedAtUtc) : [], [route, geometry, startedAtUtc]);
  if (!geometry?.hasExtent) return null;
  const active = routePosition(timeline, elapsed);
  return <figure className={styles.routeCursor}>
    <svg viewBox="0 0 200 200" role="img" aria-labelledby={title}>
      <title id={title}>Strecke des Laufs. Der markierte Punkt entspricht der Zeit in der Pulskurve. Norden oben.</title>
      {[50, 100, 150].map(position => <g key={position}><line x1="12" x2="188" y1={position} y2={position} /><line y1="12" y2="188" x1={position} x2={position} /></g>)}
      {geometry.segments.map((segment, index) => <path key={index} d={segment.map((point, i) => `${i ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ")} fill="none" stroke="var(--color-accent)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />)}
      <circle cx={geometry.start.x} cy={geometry.start.y} r="3.5" fill="var(--color-accent)" stroke="white" />
      <circle cx={geometry.end.x} cy={geometry.end.y} r="5.5" fill="none" stroke="var(--color-ink)" strokeWidth="1.3" />
      {active && <g data-route-cursor="true"><circle cx={active.x} cy={active.y} r="8" fill="white" fillOpacity=".9" /><circle cx={active.x} cy={active.y} r="4.5" fill="#9a5b00" stroke="white" strokeWidth="1.5" /></g>}
      <text x="182" y="17" textAnchor="middle">N</text>
    </svg>
    <figcaption>{!timeline.length ? "Zeitbezug fehlt" : elapsed == null ? "Punkt folgt der Kurve" : active ? "Position zur Auswahl" : "Hier fehlen GPS-Punkte"}</figcaption>
  </figure>;
}
