"use client";

import { useEffect, useId, useState } from "react";
import { de, de0 } from "@/lib/format";
import { finite, paceLabel } from "@/lib/garmin";
import { routeDate } from "@/lib/run-routes";
import { routeSegments, type RouteSegmentsData } from "@/lib/route-segments";
import styles from "./RouteSegments.module.css";

const path = (points: number[][]) => points.map(([x, y], index) => `${index ? "L" : "M"}${x},${y}`).join(" ");
const lengthLabel = (meters: number) => de(meters / 1000, meters % 1000 === 0 ? 0 : 1);

export function RouteSegments({ activityId }: { activityId: string }) {
  const id = useId();
  const [open, setOpen] = useState(false), [index, setIndex] = useState(0);
  const [data, setData] = useState<RouteSegmentsData | null>(null), [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const refresh = () => setRevision(value => value + 1);
    window.addEventListener("milon:data-refresh", refresh);
    window.addEventListener("run-analysis-updated", refresh);
    return () => { window.removeEventListener("milon:data-refresh", refresh); window.removeEventListener("run-analysis-updated", refresh); };
  }, []);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setData(null); setError(""); setIndex(0);
    routeSegments(activityId, controller.signal).then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Abschnitte konnten nicht geladen werden."); });
    return () => controller.abort();
  }, [activityId, open, revision]);
  const current = data?.activity_id === activityId ? data : null;
  const section = current?.sections[index];
  return <div className={styles.section}>
    <button className={styles.toggle} type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}><span>Streckenabschnitte vergleichen</span><span aria-hidden="true">{open ? "−" : "+"}</span></button>
    {open && <div id={id} className={styles.content}>
      {error ? <p className={styles.note} role="alert">{error} <button type="button" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></p> : !current ? <p className={styles.note} role="status">Abschnitte werden räumlich zugeordnet …</p> : current.status !== "ready" || !section ? <p className={styles.note}>{current.reason}</p> : <>
        <div className={styles.header}><strong>Wo verändert sich dein Lauf?</strong><span>Lauf vom {routeDate(current.selected.started_at).split(" · ")[0]} · GPS-Abschnitte</span></div>
        <div className={styles.body}>
          <svg viewBox="0 0 200 200" className={styles.map} aria-label={`Strecke mit ausgewähltem Abschnitt ${lengthLabel(section.start_m)} bis ${lengthLabel(section.end_m)} Kilometer`}>
            <path className={styles.route} d={path(current.contour)} />
            {current.sections.map((part, position) => <g key={part.index}>
              <path className={styles.hit} d={path(part.contour)} onClick={() => setIndex(position)}><title>Abschnitt {lengthLabel(part.start_m)}–{lengthLabel(part.end_m)} km auswählen</title></path>
            </g>)}
            <path className={styles.highlight} d={path(section.contour)} />
            {section.contour[0] && <circle className={styles.start} cx={section.contour[0][0]} cy={section.contour[0][1]} r="3" />}
          </svg>
          <div className={styles.data}>
            <div className={styles.selector}><label htmlFor={`${id}-select`}>GPS-km</label><select id={`${id}-select`} value={index} onChange={event => setIndex(Number(event.target.value))}>{current.sections.map((part, position) => <option key={part.index} value={position}>{lengthLabel(part.start_m)}–{lengthLabel(part.end_m)} km</option>)}</select><span>{section.n} {section.n === 1 ? "Vergleichslauf" : "Vergleichsläufe"}</span></div>
            <table className={styles.table}><caption className={styles.srOnly}>Dieser Abschnitt gegenüber anderen Läufen auf derselben Strecke</caption><thead><tr><th /><th>Dieser Lauf</th><th>Median</th><th>Spanne</th></tr></thead><tbody>{(["pace_seconds", "avg_hr"] as const).map(metric => {
              const value = section.metrics[metric], pace = metric === "pace_seconds";
              const format = (number: number | null) => pace ? paceLabel(number) : de0(number);
              return <tr key={metric}><th>{pace ? "Pace" : "Ø Puls"}<small>{pace ? "min/km" : "bpm"}</small></th><td className={styles.current}>{format(value.selected)}</td><td>{format(value.median)}</td><td>{finite(value.min) && finite(value.max) ? value.min === value.max ? format(value.min) : `${format(value.min)}–${format(value.max)}` : "–"}</td></tr>;
            })}</tbody></table>
            <div className={styles.navigation}><button type="button" disabled={index === 0} aria-label="Vorheriger Abschnitt" onClick={() => setIndex(value => value - 1)}>←</button><input aria-label="Streckenabschnitt auswählen" type="range" min="0" max={current.sections.length - 1} step="1" value={index} onChange={event => setIndex(Number(event.target.value))} aria-valuetext={`${lengthLabel(section.start_m)} bis ${lengthLabel(section.end_m)} Kilometer`} /><button type="button" disabled={index === current.sections.length - 1} aria-label="Nächster Abschnitt" onClick={() => setIndex(value => value + 1)}>→</button></div>
          </div>
        </div>
        {!section.selected && <p className={styles.note}>Dieser Abschnitt enthält eine Pause, eine Lücke oder unzureichende Messwerte.</p>}
        {section.selected && section.selected.avg_hr == null && <p className={styles.note}>Für den Puls sind weniger als 90 % des Abschnitts zeitlich abgedeckt.</p>}
        <p className={styles.note}>{section.n === 0 ? "Noch keine geeignete Wiederholung für diesen Abschnitt." : section.n === 1 ? "Eine Wiederholung: noch keine Streuung ablesbar." : "Spanne = kleinster bis größter beobachteter Wert."} {section.omitted_runs > 0 ? `${section.omitted_runs} von ${current.cohort_runs} passenden Läufen wegen Startversatz, Mehrdeutigkeit, Lücken oder fehlenden Werten nicht zugeordnet.` : ""} Wetter und Trainingsziel wirken mit.</p>
        <details className={styles.method}><summary>Zuordnung und Datenbasis</summary><p>{current.method}</p></details>
      </>}
    </div>}
  </div>;
}
