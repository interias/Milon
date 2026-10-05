"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { bodyProgress, type BodyProgressData, type BodyProgressObservation } from "@/lib/body-progress";
import { measurementDate, formatCm, signedCm } from "@/lib/circumferences";
import { Card } from "@/components/ui";
import styles from "./BodyProgress.module.css";

const range = (observation: BodyProgressObservation) => observation.first_date
  ? `${measurementDate(observation.first_date)}${observation.last_date !== observation.first_date ? `–${measurementDate(observation.last_date!)}` : ""}` : "keine Daten";

function Change({ value, unit }: { value: number | null; unit: string }) {
  return <strong className={styles.change}>{signedCm(value)} <small>{unit}</small></strong>;
}

function ObservationRow({ label, detail, baseline, current, delta, unit, countLabel, missing }: {
  label: string; detail: string; baseline: BodyProgressObservation; current: BodyProgressObservation;
  delta: number | null; unit: string; countLabel: string; missing: string;
}) {
  return <div className={styles.row}>
    <div className={styles.name}><strong>{label}</strong><span>{detail}</span></div>
    <div className={styles.values}><span>{formatCm(baseline.value)} <i>→</i> <b>{formatCm(current.value)}</b> {unit}</span>
      <small>{baseline.count} → {current.count} {countLabel} · {range(baseline)} → {range(current)}</small>
      {delta == null && <small>{missing}</small>}
    </div>
    <Change value={delta} unit={unit} />
  </div>;
}

export function BodyProgress({ revision = 0 }: { revision?: number }) {
  const [weeks, setWeeks] = useState(8), [measure, setMeasure] = useState("abdomen_navel");
  const [data, setData] = useState<BodyProgressData | null>(null), [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    bodyProgress(weeks, measure, controller.signal).then(value => { setData(value); setError(""); })
      .catch(error => { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "Daten konnten nicht geladen werden."); });
    return () => controller.abort();
  }, [weeks, measure, revision, retry]);
  const current = data?.weeks === weeks && data?.circumference.key === measure ? data : null;
  return <section aria-label="Körperfortschritt gemeinsam einordnen" className={styles.root}><Card>
    <header className={styles.header}><h2>Körperfortschritt</h2>
      <div className={styles.period} aria-label="Vergleichszeitraum">{[4, 8, 12].map(value => <button key={value} type="button" aria-pressed={weeks === value} onClick={() => setWeeks(value)}>{value} W</button>)}</div>
    </header>
    <p className={styles.intro}>Umfang, Gewicht und Kraft · erste → letzte 14 Tage.</p>
    <div className={styles.toolbar}><label>Messstelle<select value={measure} onChange={event => setMeasure(event.target.value)}><option value="abdomen_navel">Bauch · Nabelhöhe</option><option value="waist_narrowest">Taille · schmalste Stelle</option></select></label>
      {current && <span>{measurementDate(current.start, true)} – {measurementDate(current.end, true)}</span>}
    </div>
    {error ? <p role="alert" className={styles.error}>{error} <button type="button" onClick={() => setRetry(value => value + 1)}>Erneut laden</button></p> : !current ? <p className={styles.note} role="status">Vergleich wird geladen …</p> : <>
      <div className={styles.rows}>
        <ObservationRow label={current.circumference.name} detail={current.circumference.site} baseline={current.circumference.baseline}
          current={current.circumference.current} delta={current.circumference.delta} unit="cm" countLabel="Messungen"
          missing="Für den Vergleich braucht es Messungen in beiden Fenstern." />
        <ObservationRow label="Gewichtsmittel" detail="Alle erfassten Messtage" baseline={current.weight.baseline}
          current={current.weight.current} delta={current.weight.delta} unit="kg" countLabel="Messtage"
          missing="Für den Vergleich sind je drei Messtage nötig." />
        <div className={styles.row}><div className={styles.name}><strong>Kraftleistung</strong><span>Gleiche Übungen · e1RM</span></div>
          <div className={styles.values}><span><b>{current.strength.exercises.length}</b> vergleichbare Übungen · {current.strength.groups} Muskelgruppen</span>
            {current.strength.delta_pct == null && <small>Für eine gemeinsame Einordnung fehlen wiederholte Übungen.</small>}
            {current.strength.unmatched_exercises > 0 && <small>{current.strength.unmatched_exercises} weitere Übungen nicht vergleichbar.</small>}
          </div><Change value={current.strength.delta_pct} unit="%" />
        </div>
      </div>
      <p className={styles.note}>Beschreibender Vergleich · kein Körperfett- oder Muskelmassennachweis.</p>
      <details className={styles.method}><summary>Vergleichsfenster & Datenbasis</summary>
        <p>Start: {measurementDate(current.baseline.start, true)} – {measurementDate(current.baseline.end, true)}. Jetzt: {measurementDate(current.current.start, true)} – {measurementDate(current.current.end, true)}. Alle Zeilen vergleichen diese beiden 14-Tage-Fenster; fehlende Werte werden nicht fortgeschrieben.</p>
        <p>Umfang: Median derselben Messstelle mit bestätigtem Messprotokoll. Gewicht: Mittel der Tagesmittel, mindestens drei Messtage je Fenster. Die Mindestmengen und Zeitfenster sind Darstellungsregeln, kein Signifikanznachweis.</p>
        {current.circumference.ignored_measurements > 0 && <p>{current.circumference.ignored_measurements} Umfangsmessungen mit unbekanntem oder abweichendem Protokoll bleiben ausgeschlossen.</p>}
        <p>Kraft: Median des besten e1RM je Trainingstag und Übung (Epley, höchstens 12 Wiederholungen). Nur identische Übungsnamen mit je zwei Trainingstagen in beiden Fenstern; für die gemeinsame Änderung mindestens drei Übungen aus zwei Muskelgruppen, nach Gruppen gleich gewichtet. Gerät, Technik und Bewegungsumfang müssen vergleichbar bleiben. Neue oder weggefallene Übungen bleiben außerhalb dieses Vergleichs{current.strength.changed_exercises > 0 ? ` (${current.strength.changed_exercises} Übungen nur in einem Fenster)` : ""}. Kraftleistung belegt keine erhaltene Muskelmasse.</p>
        {!!current.strength.exercises.length && <div className={styles.tableWrap}><table><caption>Verglichene Übungen · e1RM in kg</caption><thead><tr><th>Übung</th><th>Start</th><th>Jetzt</th><th>Δ</th><th>Trainingstage</th></tr></thead><tbody>{current.strength.exercises.map(row => <tr key={row.exercise}><th><Link href={`/kraft/${encodeURIComponent(row.exercise)}`}>{row.exercise}</Link></th><td>{formatCm(row.baseline.value)}</td><td>{formatCm(row.current.value)}</td><td>{signedCm(row.delta_pct)} %</td><td>{row.baseline.count} → {row.current.count}</td></tr>)}</tbody></table></div>}
      </details>
    </>}
  </Card></section>;
}
