"use client";

import { useEffect, useId, useState } from "react";
import { mechanicsApi, type RunningLoadData } from "@/lib/run-mechanics";
import { de } from "@/lib/format";
import styles from "./RunningLoad.module.css";

const dateLabel = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });

export function RunningLoad() {
  const [data, setData] = useState<RunningLoadData | null>(null), [error, setError] = useState("");
  const [weeks, setWeeks] = useState(4), [revision, setRevision] = useState(0), [selected, setSelected] = useState<string | null>(null);
  const chartId = useId();
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    mechanicsApi.load(weeks, controller.signal).then(result => { if (!controller.signal.aborted) setData(result); })
      .catch(reason => { if (!controller.signal.aborted) setError(String(reason)); });
    return () => controller.abort();
  }, [weeks, revision]);
  useEffect(() => {
    const refresh = () => setRevision(current => current + 1);
    window.addEventListener("milon:data-refresh", refresh);
    return () => window.removeEventListener("milon:data-refresh", refresh);
  }, []);
  const active = data?.weeks.find(week => week.week === selected) ?? data?.weeks.filter(week => week.runs > 0).at(-1) ?? data?.weeks.at(-1);
  const maximum = Math.max(5, ...(data?.weeks.flatMap(week => [week.distance_km ?? 0, week.impact_load_km ?? 0]) ?? []));
  const dateTicks = new Set(Array.from({ length: Math.min(4, data?.weeks.length ?? 0) }, (_, index) => Math.round(index * ((data?.weeks.length ?? 1) - 1) / 3)));
  return <section className={styles.section} aria-label="Mechanische Laufbelastung">
    <header className={styles.header}><div><h2>Kilometer & mechanische Belastung</h2><p>Gelaufene Strecke und Garmins Impact Load · gleiche Läufe</p></div><div className={styles.period} aria-label="Zeitraum">{[4, 8, 12].map(count => <button key={count} onClick={() => { setWeeks(count); setSelected(null); }} aria-pressed={weeks === count}>{count} W</button>)}</div></header>
    {error && <p className={styles.empty} role="alert">{error} <button onClick={() => setRevision(current => current + 1)}>Erneut laden</button></p>}
    {!data ? !error && <p className={styles.empty} role="status">Laufbelastung wird geladen …</p> : <>
      <div className={styles.legend}><span><i className={styles.distanceKey} />Distanz · km</span><span><i className={styles.impactKey} />Impact Load · äquivalente km</span><span><i className={styles.legKey} />Beintraining</span></div>
      <div className={styles.chart} role="group" aria-labelledby={chartId}><span id={chartId} className="sr-only">Wochenvergleich. Woche wählen für Details.</span>{data.weeks.map((week, index) => <button key={week.week} className={week.week === active?.week ? styles.selected : ""} aria-pressed={week.week === active?.week} onClick={() => setSelected(week.week)} aria-label={`Woche ab ${dateLabel(week.week)}: ${week.paired_runs} Läufe mit Belastungswert, ${week.leg_days.length} Beintage`}><div className={styles.bars}>{week.paired_runs ? <><i className={styles.distanceBar} style={{ height: `${Math.max(2, (week.distance_km ?? 0) / maximum * 100)}%` }} /><i className={styles.impactBar} style={{ height: `${Math.max(2, (week.impact_load_km ?? 0) / maximum * 100)}%` }} /></> : <span className={styles.noData}>–</span>}</div><div className={styles.dayMarkers}>{week.leg_days.map(day => <i key={day} title={`Beintraining ${dateLabel(day)}`} />)}</div><span className={`${styles.weekDate} ${dateTicks.has(index) ? "" : styles.hiddenDate}`} aria-hidden="true">{dateLabel(week.week)}</span></button>)}</div>
      {active && <div className={styles.readout} aria-live="polite"><div><span>Woche ab {dateLabel(active.week)}{active.provisional ? " · läuft" : ""}</span><strong>{active.distance_km == null ? "–" : de(active.distance_km, 1)} <small>km</small><em>/</em>{active.impact_load_km == null ? "–" : de(active.impact_load_km, 1)} <small>äq. km</small></strong></div><p>{active.paired_runs}/{active.runs} Läufe mit vergleichbarer Datenbasis<br />{active.leg_days.length} {active.leg_days.length === 1 ? "Tag" : "Tage"} mit Beintraining</p></div>}
      {active && active.runs > active.paired_runs && <p className={styles.note}>Gesamtstrecke {de(active.all_distance_km, 1)} km; {active.runs - active.paired_runs} {active.runs - active.paired_runs === 1 ? "Lauf ohne bestätigten Impact-Wert" : "Läufe ohne bestätigten Impact-Wert"} bleiben aus dem Balkenvergleich heraus.</p>}
      {data.tolerance.available ? <div className={styles.tolerance}><span>Garmin · Lauftoleranz <small>{data.tolerance.date ? dateLabel(data.tolerance.date) : ""}{data.tolerance.stale ? " · älterer Stand" : ""}</small></span><strong>{de(data.tolerance.tolerance_km, 1)} <small>äq. km</small></strong>{data.tolerance.acute_load_km != null && <p>Akute Impact Load: {de(data.tolerance.acute_load_km, 1)} äq. km</p>}<p>Garmins Einschätzung aus deinem Verlauf. Kein individuelles Verletzungsrisiko und keine sichere Obergrenze.</p></div> : <p className={styles.note}>{data.tolerance.reason}</p>}
      <details className={styles.method}><summary>Datenbasis & Bedeutung</summary><p>{data.method}</p><p>Leere Wochen bedeuten keine geeigneten Aufzeichnungen. Hevy-Beintage sind gesonderte Marker und kein Teil von Garmins Laufbelastung.</p></details>
    </>}
  </section>;
}
