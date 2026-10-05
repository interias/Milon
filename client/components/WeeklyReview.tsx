"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import Link from "next/link";
import { Card } from "@/components/ui";
import { weeklyJournal, type JournalDay, type WeeklyJournal } from "@/lib/weekly-journal";
import { de, de0, dm } from "@/lib/format";
import styles from "./WeeklyReview.module.css";
import { useSyncFeedback } from "@/components/SyncFeedback";

const delta = (value: number, unit: string, digits = 1) => `${value > 0 ? "+" : ""}${de(value, digits)} ${unit} zur Vorwoche`;
const sleepTime = (hours: number | null | undefined) => hours == null ? "—" : `${Math.floor(Math.round(hours * 60) / 60)}:${String(Math.round(hours * 60) % 60).padStart(2, "0")} h`;

function JournalCell({ day, selected, fresh, onSelect, onKeyDown }: { day: JournalDay; selected: boolean; fresh: boolean; onSelect: () => void; onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void }) {
  const runningKm = day.runs.reduce((sum, run) => sum + run.distance_km, 0);
  const energy = day.checkin?.energy;
  const dayLabel = new Date(`${day.date}T12:00:00Z`).toLocaleDateString("de-DE", { timeZone: "UTC", weekday: "short" });
  const asset = day.runs.length ? "easy" : day.strength.length ? "strength" : null;
  return <button type="button" className={`${styles.day} ${selected ? styles.selectedDay : ""} ${fresh ? "milon-new-data" : ""}`}
    aria-pressed={selected} aria-controls="journal-day-detail" aria-label={`${dayLabel}, ${dm(day.date)} · Tagesdetails${fresh ? " · Neue Daten" : ""}`}
    onClick={onSelect} onKeyDown={onKeyDown}>
    <div className={styles.dayHeading}><strong>{dayLabel}</strong><span>{dm(day.date)}</span></div>
    {fresh && <small className={styles.fresh}>Neu</small>}
    {asset && <div className={styles.illustration} aria-hidden="true">{/* eslint-disable-next-line @next/next/no-img-element */}<img src={`/img/activity/${asset}.png`} alt="" /></div>}
    <div className={styles.training}>
      {day.runs.length ? <span className={styles.run}><span className={styles.marker} />{de(runningKm, 1)} km</span> : <span className={styles.missing}>— <small>Laufen</small></span>}
      {day.strength.length ? <span className={styles.strength}><span className={styles.marker} />Gym{day.strength.length > 1 ? ` · ${day.strength.length}×` : ""}</span> : <span className={styles.missing}>— <small>Gym</small></span>}
    </div>
    <div className={styles.sleep}><span>Schlaf</span><strong title={day.sleep ? `${day.sleep.label} · ${day.sleep.hours == null ? "Schlafzeit unbekannt" : "Hauptschlaf"}` : "Keine Hauptschlafphase erfasst"}>{sleepTime(day.sleep?.hours)}</strong>
      <div className={styles.sleepTrack} aria-hidden="true" title="Schlafdauer · Skala 0–10 Stunden">{day.sleep?.hours != null && <div style={{ width: `${Math.min(100, day.sleep.hours * 10)}%` }} />}</div>
    </div>
    <div className={styles.energy}><span>Energie</span>{energy == null ? <strong className={styles.missing}>—</strong> : <div className={styles.dots} role="img" aria-label={`Energie ${energy} von 5`} title={`Energie ${energy} von 5`}>{[1, 2, 3, 4, 5].map(value => <i key={value} className={value <= energy ? styles.filled : ""} />)}<small>{energy}/5</small></div>}</div>
  </button>;
}

function DayDetail({ day, onClose }: { day: JournalDay; onClose: () => void }) {
  const time = (stamp: string) => stamp.slice(11, 16);
  return <section id="journal-day-detail" className={styles.dayDetail} aria-label={`Tagesdetails ${dm(day.date)}`}>
    <div className={styles.detailHeading}><h3>{new Date(`${day.date}T12:00:00Z`).toLocaleDateString("de-DE", { timeZone: "UTC", weekday: "long", day: "2-digit", month: "2-digit" })}</h3><button type="button" aria-label="Tagesdetails schließen" onClick={onClose}>×</button></div>
    <div className={styles.detailGrid}>
      <div><h4>Training</h4>{!day.runs.length && !day.strength.length && <p>Keine Einheit erfasst.</p>}
        {day.runs.map((run, index) => <p key={`run-${index}`}>{run.activity_id ? <Link href={`/laufen/${encodeURIComponent(run.activity_id)}`}>{time(run.started_at)} · Lauf, {de(run.distance_km, 1)} km →</Link> : <span>{time(run.started_at)} · Lauf, {de(run.distance_km, 1)} km</span>}<small>{de(run.minutes, 0)} Minuten</small></p>)}
        {day.strength.map((workout, index) => <div className={styles.workout} key={`strength-${index}`}><p>{time(workout.started_at)} · {workout.title}</p><div className={styles.exerciseLinks}>{workout.exercises.length ? workout.exercises.map(exercise => <Link key={exercise} href={`/kraft/${encodeURIComponent(exercise)}`}>{exercise}</Link>) : <Link href="/kraft">Kraftübersicht →</Link>}</div></div>)}
      </div>
      <div><h4>Schlaf & Tagesgefühl</h4>{day.sleep ? <p><Link href={`/gesundheit?night=${day.date}`}>{sleepTime(day.sleep.hours)} Schlaf · {day.sleep.label} →</Link>{day.sleep.hours === null && <small>Schlafphasen unvollständig</small>}</p> : <p>Keine Nacht erfasst.</p>}
        <p>Energie {day.checkin?.energy == null ? "—" : `${day.checkin.energy}/5`}{day.checkin?.training_effort != null ? ` · Anstrengung ${day.checkin.training_effort}/5` : ""}</p>
        {day.steps != null && <p>{de0(day.steps)} Schritte</p>}
      </div>
    </div>
  </section>;
}

export function WeeklyReview() {
  const [offset, setOffset] = useState(0), [revision, setRevision] = useState(0);
  const [data, setData] = useState<WeeklyJournal | null>(null), [error, setError] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const calendar = useRef<HTMLDivElement>(null);
  const feedback = useSyncFeedback();
  const freshDays = new Set(feedback ? [...feedback.runs, ...feedback.nights, ...feedback.workouts, ...feedback.weights, ...feedback.nutrition].map(item => item.date) : []);
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
  const active = data?.days.find(day => day.date === selected);
  useEffect(() => {
    if (active && window.matchMedia("(max-width: 700px)").matches) {
      document.getElementById("journal-day-detail")?.scrollIntoView({ block: "nearest",
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
  }, [active?.date]);
  function moveDay(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "Escape"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Escape") { setSelected(null); return; }
    const next = event.key === "Home" ? 0 : event.key === "End" ? 6 : Math.max(0, Math.min(6, index + (["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1)));
    setSelected(data!.days[next].date);
    calendar.current?.querySelectorAll<HTMLButtonElement>("button")[next]?.focus();
  }
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
      <div className={styles.calendar} ref={calendar} aria-label="Tagebuch · Tage antippen oder mit Pfeiltasten auswählen">{data.days.map((day, index) => <JournalCell key={day.date} day={day} selected={selected === day.date} fresh={freshDays.has(day.date)} onSelect={() => setSelected(previous => previous === day.date ? null : day.date)} onKeyDown={event => moveDay(event, index)} />)}</div>
      {active ? <DayDetail key={active.date} day={active} onClose={() => { setSelected(null); calendar.current?.querySelector<HTMLButtonElement>("button[aria-pressed=true]")?.focus(); }} /> : <p className={styles.exploreHint}>Tag antippen · Training und Nacht ansehen</p>}
      <div className={styles.footer}><p><strong>Gewicht {summary!.weight_delta_kg == null ? "—" : `${summary!.weight_delta_kg > 0 ? "+" : ""}${de(summary!.weight_delta_kg, 2)} kg`}</strong> · Wochenmittel, {summary!.weight_days}/7 Messtage, davor {summary!.previous_weight_days}/7</p>
        <p><strong>{de0(summary!.steps_avg)} Schritte/Tag</strong> · {summary!.steps_days}/7 Tage erfasst · {summary!.checkin_days}/7 Check-ins</p></div>
      <p className={styles.note}>{data.note}{data.sources.length > 1 ? " Diese Woche enthält einen Uhrenwechsel." : ""}</p>
    </>}
  </Card>;
}
