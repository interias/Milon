"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { de, de0 } from "@/lib/format";
import { routeDate } from "@/lib/run-routes";
import { runInsightsApi, type WeeklyRunZones, type ZoneSummary } from "@/lib/run-insights";
import styles from "./RunIntensityZones.module.css";

const colors = ["#3978bb", "#208568", "#b38108", "#d26528", "#bb3c4e"];
function ZoneBar({ data }: { data: ZoneSummary }) {
  const total = Math.max(1, data.total_seconds);
  return <span className={styles.bar} aria-hidden="true">
    {data.zones.filter(zone => zone.seconds > 0).map(zone => <span key={zone.zone} style={{ width: `${zone.seconds / total * 100}%`, background: colors[zone.zone - 1] }} />)}
    {data.outside_seconds > 0 && <span className={styles.outside} style={{ width: `${data.outside_seconds / total * 100}%` }} />}
    {data.unknown_seconds > 0 && <span className={styles.unknown} style={{ width: `${data.unknown_seconds / total * 100}%` }} />}
  </span>;
}
function ZoneLegend() {
  return <div className={styles.legend}>{colors.map((color, index) => <span key={index}><i style={{ background: color }} />Z{index + 1}</span>)}<span><i className={styles.outside} />Außerhalb</span><span><i className={styles.unknown} />Ohne Puls</span></div>;
}
function ZoneValues({ data }: { data: ZoneSummary }) {
  return <>
    <p className={styles.valuesLabel}>Minuten je Zone · Pulsbereiche in bpm</p>
    <div className={styles.zoneValues}>{data.zones.map(zone => <div key={zone.zone} style={{ "--zone-color": colors[zone.zone - 1] } as CSSProperties}><span>Z{zone.zone}</span><strong aria-label={`${de(zone.seconds / 60, 1)} Minuten`}>{de(zone.seconds / 60, 1)}</strong><span>{de0(Math.ceil(zone.hr_low))}–{de0(zone.zone === 5 ? Math.floor(zone.hr_high) : Math.ceil(zone.hr_high) - 1)}</span></div>)}</div>
    {(data.outside_seconds > 0 || data.unknown_seconds > 0) && <div className={styles.missing}>{data.outside_seconds > 0 && <span>Außerhalb Z1–5: {de(data.outside_seconds / 60, 1)} min</span>}{data.unknown_seconds > 0 && <span>Ohne Puls: {de(data.unknown_seconds / 60, 1)} min</span>}</div>}
  </>;
}

export function RunIntensityZones({ data }: { data: ZoneSummary }) {
  return <div className={styles.content}>
    <div className={styles.caption}><span>{data.label}{data.hr_max != null ? ` · HFmax ${de0(data.hr_max)} bpm` : ""}</span><span>{de(data.total_seconds / 60, 1)} min ausgewertet</span></div>
    <ZoneBar data={data} />
    <ZoneValues data={data} />
    <details className={styles.method}><summary>Zonen & Berechnung</summary><p className={styles.note}>{data.method}</p></details>
  </div>;
}

export function RunWeeklyZones() {
  const [data, setData] = useState<WeeklyRunZones | null>(null), [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const refresh = () => setRevision(value => value + 1);
    window.addEventListener("milon:data-refresh", refresh);
    return () => window.removeEventListener("milon:data-refresh", refresh);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    runInsightsApi.zones(controller.signal).then(value => { if (!controller.signal.aborted) setData(value); }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Intensität konnte nicht geladen werden."); });
    return () => controller.abort();
  }, [revision]);
  return <details className={styles.weekly}><summary>Intensität · Wochen <span>Minuten je Pulszone</span></summary>
    {error ? <p className={styles.note} role="alert">{error} <button type="button" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></p> : !data ? <p className={styles.note} role="status">Pulszonen werden geladen …</p> : <>
      <div className={styles.caption}><span>{data.label}{data.hr_max != null ? ` · HFmax ${de0(data.hr_max)} bpm` : ""}</span><span>Letzte 8 Wochen</span></div>
      <ZoneLegend />
      {!data.weeks.length ? <p className={styles.note}>Noch keine Garmin-Läufe für diesen Zeitraum.</p> : <div className={styles.weeks}>{[...data.weeks].reverse().map(week => {
        const row = <><span>ab {routeDate(week.week).slice(0, 5)}</span><span><ZoneBar data={week} /></span><strong>{week.runs ? <>{de(week.total_seconds / 60, 0)} <small>min</small></> : "–"}</strong><span className={styles.runCount}>{week.runs ? `${week.runs} ${week.runs === 1 ? "Lauf" : "Läufe"} · Zonen aufklappen` : "Keine geeignete Aufzeichnung"}{week.excluded_runs > 0 ? ` · ${week.excluded_runs} ausgeschlossen` : ""}</span></>;
        return week.runs ? <details key={week.week} className={styles.weekDetail}><summary className={styles.week}>{row}</summary><ZoneValues data={week} /></details> : <div key={week.week} className={styles.week}>{row}</div>;
      })}</div>}
      <details className={styles.method}><summary>Zonen & Berechnung</summary><p className={styles.note}>{data.method}</p></details>
    </>}
  </details>;
}
