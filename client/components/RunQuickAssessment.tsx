"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { api, type StandardizedHr } from "@/lib/api";
import { de, de0 } from "@/lib/format";
import { finite, paceLabel, type GarminActivity } from "@/lib/garmin";
import type { RunInsights } from "@/lib/run-insights";
import styles from "./RunQuickAssessment.module.css";

const EFFECT_LABELS = ["Kein wesentlicher Reiz", "Gering", "Erhaltend", "Aufbauend", "Stark aufbauend", "Sehr hoch"];
const dateLabel = (value: string | undefined) => {
  if (!value) return "nicht verfügbar";
  const match = value.match(/^(\d{4})-(\d{2})(?:-(\d{2}))?/);
  return match ? `${match[3] ? `${match[3]}.` : ""}${match[2]}.${match[1]}` : "nicht verfügbar";
};

function EffectValue({ label, value }: { label: string; value: number | null }) {
  const rounded = finite(value) && value >= 0 && value <= 5 ? Math.round(value * 10) / 10 : null;
  return <div className={styles.effectRow}><span>{label}</span><strong>{de(rounded, 1)} <small>/ 5</small></strong><span>{rounded == null ? "Nicht erfasst" : EFFECT_LABELS[Math.floor(rounded)]}</span></div>;
}

function CurrentDevelopment() {
  const [trend, setTrend] = useState<StandardizedHr | null>(null), [error, setError] = useState(false), [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const request = useRef(0);
  useEffect(() => {
    const refresh = () => setRevision(value => value + 1);
    window.addEventListener("milon:data-refresh", refresh);
    window.addEventListener("run-analysis-updated", refresh);
    return () => { window.removeEventListener("milon:data-refresh", refresh); window.removeEventListener("run-analysis-updated", refresh); };
  }, []);
  useEffect(() => {
    const version = ++request.current;
    let active = true;
    setLoading(true); setError(false);
    api.runStandardizedHr().then(value => {
      if (active && version === request.current) setTrend(value);
    }).catch(() => {
      if (active && version === request.current) setError(true);
    }).finally(() => {
      if (active && version === request.current) setLoading(false);
    });
    return () => { active = false; };
  }, [revision]);

  const series = trend?.pace_series.find(item => item.pace_seconds === 360) ?? trend?.pace_series[0];
  const latest = series?.points.at(-1);
  const usable = latest && ["ok", "provisional", "sensitive"].includes(latest.status) && finite(latest.hr);
  const comparison = usable && series?.comparison?.to_month === latest.month && finite(series.comparison.delta) ? series.comparison : null;
  return <>
    {loading ? <p className={styles.empty} role="status">Aktueller Stand wird geladen …</p> : error ? <div className={styles.empty} role="alert"><p>Entwicklung konnte nicht geladen werden.</p><button type="button" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></div> : <>
      {usable ? <>
        <p className={styles.value}>{comparison ? `${comparison.delta > 0 ? "+" : ""}${de(comparison.delta, 1)}` : de(latest.hr, 1)} <small>bpm</small></p>
        <p className={styles.verdict}>{comparison ? comparison.verdict === "lower" ? "Standardisierter Puls niedriger" : comparison.verdict === "higher" ? "Standardisierter Puls höher" : "Unterschied unklar" : "Standardisierter Puls · noch kein Vergleich"}</p>
        {comparison && <p className={styles.note}>{dateLabel(comparison.from_month)} → {dateLabel(comparison.to_month)}</p>}
        {latest.status !== "ok" && <p className={styles.note}>{latest.status === "provisional" ? "Vorläufige Schätzung" : "Empfindlich gegenüber einzelnen Läufen"}</p>}
      </> : <>
        <p className={styles.emptyTitle}>Noch keine aktuelle Schätzung</p>
        <p className={styles.note}>{latest?.reasons.map(reason => reason === "Referenzpace in diesem Sensorabschnitt nicht ausreichend belegt." ? "Seit dem Sensorwechsel fehlen noch genügend vergleichbare Läufe bei dieser Pace." : reason).join(" · ") || trend?.empty_reason || "Noch nicht genügend vergleichbare Läufe."}</p>
      </>}
      {series && <p className={styles.note}>Referenz {paceLabel(series.pace_seconds)} /km · Minute {trend?.reference_minute}{latest ? ` · ${latest.runs} Läufe` : ""}</p>}
      <p className={styles.stamp}>Auswertung: {dateLabel(trend?.updated_at)}{latest ? ` · Fenster bis ${dateLabel(latest.month)}` : ""}</p>
    </>}
    <Link href="/laufen#running-fitness" scroll={false} className={styles.link}>Entwicklung ansehen <span aria-hidden="true">→</span></Link>
  </>;
}

export function RunQuickAssessment({ data, insights, insightsError }: { data: GarminActivity; insights: RunInsights | null; insightsError?: string }) {
  const id = useId();
  const drift = insights?.available ? insights.drift : null;
  const observed = !insightsError && drift?.status === "observed" && finite(drift.value_pct);
  const change = observed ? Math.round(drift.value_pct! * 10) / 10 : null;
  return <div className={styles.grid}>
    <section className={styles.card} aria-labelledby={`${id}-effect`}>
      <div className={styles.heading}><h2 id={`${id}-effect`}>Trainingsreiz</h2><a href="https://www.garmin.com/en-AU/garmin-technology/running-science/physiological-measurements/training-effect/" target="_blank" rel="noreferrer" className={styles.scaleLink}>Skala <span aria-hidden="true">↗</span></a></div>
      <p className={styles.subtitle}>Dieser Lauf · Garmin-Schätzung</p>
      <div className={styles.effects}><EffectValue label="Aerob" value={data.summary.training_effect} /><EffectValue label="Anaerob" value={data.summary.anaerobic_training_effect} /></div>
      <p className={styles.note}>Höher ist nicht automatisch besser; der Reiz sollte zum Trainingsziel passen.</p>
    </section>
    <section className={styles.card} aria-labelledby={`${id}-drift`}>
      <h2 id={`${id}-drift`}>Pulsstabilität</h2><p className={styles.subtitle}>Dieser Lauf · bei ähnlichem Tempo & Gefälle</p>
      {observed ? <><p className={styles.value}>{change! > 0 ? "+" : ""}{de(change, 1)} <small>%</small></p><p className={styles.verdict}>{change! > 0 ? "Pulsanstieg" : change! < 0 ? "Pulsrückgang" : "Kaum Veränderung"}</p><p className={styles.note}>{de0(drift.early_hr)} → {de0(drift.late_hr)} bpm · frühe → späte Abschnitte</p></> : <><p className={styles.emptyTitle}>{insightsError ? "Einordnung nicht verfügbar" : !insights ? "Einordnung wird geladen …" : drift?.status === "excluded" ? "Nicht vergleichbar" : "Noch nicht einzuordnen"}</p><p className={styles.note}>{insightsError || drift?.reason || (insights ? "Noch keine passende Aufzeichnung verfügbar." : "")}</p></>}
      <a href="#intensitaet" className={styles.link}>Pulsverlauf einordnen <span aria-hidden="true">↓</span></a>
    </section>
    <section className={styles.card} aria-labelledby={`${id}-development`}>
      <h2 id={`${id}-development`}>Aktuelle Entwicklung</h2><p className={styles.subtitle}>Trend über mehrere Läufe · aktueller Stand</p><CurrentDevelopment />
    </section>
  </div>;
}
