"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card } from "@/components/ui";
import { weeklyJournal, type JournalDay, type WeeklyJournal } from "@/lib/weekly-journal";
import { de, de0, dm } from "@/lib/format";
import styles from "./WeeklyReview.module.css";

const delta = (value: number, unit: string, digits = 1) => `${value > 0 ? "+" : ""}${de(value, digits)} ${unit} zur Vorwoche`;
const sleepTime = (hours: number | null | undefined) => hours == null ? "—" : `${Math.floor(Math.round(hours * 60) / 60)}:${String(Math.round(hours * 60) % 60).padStart(2, "0")} h`;

function JournalCell({ day }: { day: JournalDay }) {
  const runningKm = day.runs.reduce((sum, run) => sum + run.distance_km, 0);
  const energy = day.checkin?.energy;
  const dayLabel = new Date(`${day.date}T12:00:00Z`).toLocaleDateString("de-DE", { timeZone: "UTC", weekday: "short" });
  const asset = day.runs.length ? "easy" : day.strength.length ? "strength" : null;
  return <div className={styles.day}>
    <div className={styles.dayHeading}><strong>{dayLabel}</strong><span>{dm(day.date)}</span></div>
    {asset && <div className={styles.illustration} aria-hidden="true">{/* eslint-disable-next-line @next/next/no-img-element */}<img src={`/img/activity/${asset}.png`} alt="" /></div>}
    <div className={styles.training}>
      {day.runs.length ? <Link href="/laufen" className={styles.run} title={`${day.runs.length} erfasste ${day.runs.length === 1 ? "Laufeinheit" : "Laufeinheiten"}`}><span className={styles.marker} />{de(runningKm, 1)} km</Link> : <span className={styles.missing}>— <small>Laufen</small></span>}
      {day.strength.length ? <Link href="/kraft" className={styles.strength} title={day.strength.map(workout => workout.title).join(" · ")}><span className={styles.marker} />Gym{day.strength.length > 1 ? ` · ${day.strength.length}×` : ""}</Link> : <span className={styles.missing}>— <small>Gym</small></span>}
    </div>
    <div className={styles.sleep}><span>Schlaf</span><strong title={day.sleep ? `${day.sleep.label} · ${day.sleep.hours == null ? "Schlafzeit unbekannt" : "Hauptschlaf"}` : "Keine Hauptschlafphase erfasst"}>{sleepTime(day.sleep?.hours)}</strong>
      <div className={styles.sleepTrack} aria-hidden="true" title="Schlafdauer · Skala 0–10 Stunden">{day.sleep?.hours != null && <div style={{ width: `${Math.min(100, day.sleep.hours * 10)}%` }} />}</div>
    </div>
    <div className={styles.energy}><span>Energie</span>{energy == null ? <strong className={styles.missing}>—</strong> : <div className={styles.dots} role="img" aria-label={`Energie ${energy} von 5`} title={`Energie ${energy} von 5`}>{[1, 2, 3, 4, 5].map(value => <i key={value} className={value <= energy ? styles.filled : ""} />)}<small>{energy}/5</small></div>}</div>
  </div>;
}

export function WeeklyReview() {
  const [offset, setOffset] = useState(0), [revision, setRevision] = useState(0);
  const [data, setData] = useState<WeeklyJournal | null>(null), [error, setError] = useState(false);
  useEffect(() => {
    const refresh = () => setRevision(value => value + 1);
    window.addEventListener("milon:data-refresh", refresh);
    return () => window.removeEventListener("milon:data-refresh", refresh);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError(false);
    weeklyJournal(offset, controller.signal).then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [offset, revision]);
  const summary = data?.summary;
  return <Card className={`mt-4 ${styles.card}`}>
    <div className={styles.header}><div><h2>Deine Woche</h2><p>{data ? `${dm(data.from_date)}–${dm(data.to_date)} · sieben abgeschlossene Kalendertage` : "Training, Schlaf & Energie"}</p></div>
      <div className={styles.navigation}><button type="button" aria-label="Sieben Tage früher" title="Sieben Tage früher" disabled={offset >= 52} onClick={() => setOffset(value => value + 1)}>←</button>
        <button type="button" aria-label="Letzte abgeschlossene Woche" disabled={offset === 0} onClick={() => setOffset(0)}>Aktuell</button>
        <button type="button" aria-label="Sieben Tage später" title="Sieben Tage später" disabled={offset === 0} onClick={() => setOffset(value => value - 1)}>→</button></div>
    </div>
    {!data ? <p className={styles.empty} role={error ? "alert" : "status"}>{error ? "Wochenjournal konnte nicht geladen werden." : "Woche wird geladen …"}{error && <button type="button" onClick={() => setRevision(value => value + 1)}>Erneut laden</button>}</p> : <>
      <div className={styles.summary}>
        <div><span>Laufen · erfasst</span><strong>{de(summary!.running_km, 1)} <small>km</small></strong><p>{delta(summary!.running_delta_km, "km")}</p></div>
        <div><span>Gym · erfasst</span><strong>{summary!.strength_sessions} <small>{summary!.strength_sessions === 1 ? "Einheit" : "Einheiten"}</small></strong><p>{delta(summary!.strength_delta_sessions, "Einheiten", 0)}</p></div>
        <div><span>Schlaf · Ø</span><strong>{sleepTime(summary!.sleep_hours)}</strong><p>{summary!.sleep_nights}/7 Nächte · {data.sources.join(" / ") || "noch ohne Messung"}</p></div>
      </div>
      <div className={styles.calendar} aria-label="Tagebuch für sieben abgeschlossene Tage">{data.days.map(day => <JournalCell key={day.date} day={day} />)}</div>
      <div className={styles.footer}><p><strong>Gewicht {summary!.weight_delta_kg == null ? "—" : `${summary!.weight_delta_kg > 0 ? "+" : ""}${de(summary!.weight_delta_kg, 2)} kg`}</strong> · Wochenmittel, {summary!.weight_days}/7 Messtage, davor {summary!.previous_weight_days}/7</p>
        <p><strong>{de0(summary!.steps_avg)} Schritte/Tag</strong> · {summary!.steps_days}/7 Tage erfasst · {summary!.checkin_days}/7 Check-ins</p></div>
      <p className={styles.note}>{data.note}{data.sources.length > 1 ? " Diese Woche enthält einen Uhrenwechsel." : ""}</p>
    </>}
  </Card>;
}
