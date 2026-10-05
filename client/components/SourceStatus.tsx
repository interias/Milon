"use client";

import { useEffect, useState } from "react";
import { getSourceStatus, type SourceHealth, type SourceStatusData } from "@/lib/source-status";
import styles from "./SourceStatus.module.css";

const labels: Record<SourceHealth, string> = { ok: "Abruf aktuell", partial: "Teilweise", error: "Abruf fehlgeschlagen", never: "Noch kein Erfolg", old: "Abruf älter", not_configured: "Nicht eingerichtet" };
const categoryLabels = { available: "Vorhanden", empty: "Keine neuen Werte", error: "Abruf fehlgeschlagen", unsupported: "Nicht unterstützt", never: "Noch kein Abruf" };
const stamp = (value: string | null) => value ? new Date(value).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "Noch nicht belegt";
const date = (value: string | null) => value ? new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString("de-DE") : "Keine Daten";

export function SourceStatus() {
  const [data, setData] = useState<SourceStatusData | null>(null), [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const refresh = () => setRevision(value => value + 1);
    window.addEventListener("milon:data-refresh", refresh);
    return () => window.removeEventListener("milon:data-refresh", refresh);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    getSourceStatus(controller.signal).then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Quellenstatus nicht verfügbar."); });
    return () => controller.abort();
  }, [revision]);
  const notices = data?.sources.filter(source => ["partial", "error", "old"].includes(source.status)).length ?? 0;
  return <details className={styles.card}>
    <summary><span>Datenquellen</span><span className={notices ? styles.warning : styles.muted}>{error ? "Status nicht verfügbar" : !data ? "Wird geladen …" : notices ? `${notices} ${notices === 1 ? "Hinweis" : "Hinweise"}` : "Abruf & Messstand"}</span></summary>
    <div className={styles.content}>
      {error && <p className={styles.error} role="alert">{error} <button type="button" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></p>}
      {data && <>
        <p className={styles.intro}>Ein aktueller Abruf bedeutet, dass die Quelle geprüft wurde. Das letzte Messdatum kann auch ohne Fehler älter sein.</p>
        {!data.scheduler_enabled && <p className={styles.warning}>Die automatische Synchronisierung ist ausgeschaltet.</p>}
        <ul className={styles.sources}>{data.sources.map(source => <li key={source.key}>
          <div className={styles.rowHeader}><div><h3>{source.label}</h3><p>{source.purpose}</p></div><span className={`${styles.status} ${["partial", "error", "old"].includes(source.status) ? styles.warning : source.status === "ok" ? styles.ok : styles.muted}`}>{labels[source.status]}</span></div>
          <dl className={styles.dates}><div><dt>Letzter erfolgreicher {source.key === "health_connect" || source.key === "arboleaf" ? "Import" : "Abruf"}</dt><dd>{stamp(source.last_success_at)}</dd></div><div><dt>Neueste Messung / Eintrag</dt><dd>{date(source.latest_data_date)}</dd></div></dl>
          {source.last_attempt_at && source.status !== "ok" && <p className={styles.attempt}>Letzter Versuch · {stamp(source.last_attempt_at)}</p>}
          <p className={styles.note}>{source.note}</p>
          {source.categories.length > 0 && <details className={styles.categories}><summary>Garmin-Bereiche</summary><ul>{source.categories.map(category => <li key={category.key}><span>{category.label}</span><span className={category.status === "error" ? styles.warning : styles.muted}>{categoryLabels[category.status]}</span></li>)}</ul><p className={styles.note}>Fehlende neue VO₂max- oder HRV-Werte sind kein Verbindungsfehler. Bei Teilfehlern bleiben erfolgreich geladene Bereiche erhalten.</p></details>}
        </li>)}</ul>
        <details className={styles.explanation}><summary>Warum zwei Ruhepulswerte?</summary><p>{data.resting_hr_note}</p><p>Garmin nutzt das niedrigste 30-Minuten-Mittel eines Tages. Im bisherigen HC-Verlauf verwenden wir den kleinsten übermittelten Ruhepuls-Eintrag je Tag. Die Reihe bleibt bis zur Klärung separat.</p></details>
      </>}
    </div>
  </details>;
}
