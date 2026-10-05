"use client";

import { useEffect, useId, useState } from "react";
import Link from "next/link";
import { Card } from "./ui";
import { de, dm } from "@/lib/format";
import { overviewHistory, monthLabel, type OverviewHistoryData, type HistoryPoint } from "@/lib/overview-history";
import { MonthlyRecap } from "./MonthlyRecap";
import styles from "./OverviewHistory.module.css";

const metrics = [{ key: "body", title: "Körper", subtitle: "Gewicht · 7-Tage-Mittel", unit: "kg", digits: 1, href: "/koerper" },
  { key: "running", title: "Laufen", subtitle: "Puls bei 6:00 /km · Laufminute 30", unit: "bpm", digits: 1, href: "/laufen" },
  { key: "strength", title: "Kraft", subtitle: "Gesamtstärke · damaliger Übungskorb", unit: "Index", digits: 0, href: "/kraft" }] as const;

export function HistoryCards({ point }: { point: HistoryPoint }) {
  return <div className={`grid gap-4 md:grid-cols-3 ${styles.cards}`} key={point.month}>{metrics.map(metric => {
    const value = point[metric.key];
    return <Card key={metric.key} className="flex h-full min-w-0 flex-col"><h2 className="text-sm font-semibold">{metric.title}</h2><p className="mt-1 text-xs text-muted">{metric.subtitle}</p>
      <div className="flex-1"><p className="mt-3 font-display text-3xl font-extrabold">{value.value == null ? "—" : de(value.value, metric.digits)} <span className="text-sm font-normal text-muted">{metric.unit}</span></p>
      <p className="mt-2 text-sm">{value.change_to_now == null ? "Kein Vergleich mit heute verfügbar" : `${value.change_to_now > 0 ? "+" : ""}${de(value.change_to_now, metric.digits)} ${metric.unit === "Index" ? "Punkte" : metric.unit} bis heute`}</p>
      <p className="mt-2 text-xs text-muted">Stichtag {dm(point.as_of)} · {metric.key === "body" ? `${value.days}/7 Messtage` : metric.key === "running" ? `${value.runs} geeignete Läufe` : `${value.exercises} Übungen`}</p>
      {value.value == null && <p className="mt-2 text-xs text-muted">{value.note || "Für diesen Stichtag nicht ausreichend belegt."}</p>}
      {value.comparison_note && <p className="mt-2 text-xs text-muted">{value.comparison_note}</p>}
      {metric.key === "running" && value.status === "sensitive" && <p className="mt-2 text-xs text-muted">Schätzung empfindlich gegenüber einzelnen Läufen.</p>}
      {metric.key === "strength" && <p className="mt-2 text-xs text-muted">Aus den bis dahin gemessenen Sätzen neu berechnet. Übungswechsel können den Vergleich beeinflussen.</p>}</div>
      <Link href={metric.href} className="mt-4 w-fit py-1 text-xs font-semibold text-accent">{metric.title} ansehen →</Link>
    </Card>;
  })}</div>;
}

export function OverviewHistory({ onSelect }: { onSelect: (point: HistoryPoint | null) => void }) {
  const [data, setData] = useState<OverviewHistoryData | null>(null), [index, setIndex] = useState<number | null>(null);
  const [error, setError] = useState(false), [revision, setRevision] = useState(0);
  const id = useId();
  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    overviewHistory(controller.signal).then(value => { if (!controller.signal.aborted) { setData(value); setIndex(null); onSelect(null); } }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [revision, onSelect]);
  useEffect(() => {
    const refresh = () => setRevision(value => value + 1);
    window.addEventListener("milon:data-refresh", refresh);
    return () => window.removeEventListener("milon:data-refresh", refresh);
  }, []);
  if (!data) return <div className={styles.placeholder} role="status">{error ? <button onClick={() => setRevision(value => value + 1)}>Zeitreise erneut laden</button> : "Zeitreise wird vorbereitet …"}</div>;
  const selected = index ?? data.points.length - 1, point = data.points[selected], current = selected === data.points.length - 1;
  function change(next: number) { setIndex(next); onSelect(next === data!.points.length - 1 ? null : data!.points[next]); }
  return <div className={styles.bar}>
    <div className={styles.heading}><label htmlFor={id}>Zeitreise <span>{current ? "Heute" : monthLabel(point.month)}</span></label><MonthlyRecap months={data.points.map(value => value.month)} selectedMonth={point.month} /></div>
    <div className={styles.slider}><button type="button" aria-label="Einen Monat zurück" disabled={selected === 0} onClick={() => change(selected - 1)}>‹</button><input id={id} type="range" min="0" max={Math.max(0, data.points.length - 1)} step="1" value={selected} disabled={data.points.length < 2} aria-valuetext={current ? "Heute" : monthLabel(point.month)} onChange={event => change(Number(event.target.value))} /><button type="button" aria-label="Einen Monat vor" disabled={current} onClick={() => change(selected + 1)}>›</button></div>
    <div className={styles.labels}><span>{monthLabel(data.points[0].month)}</span>{!current && <button type="button" onClick={() => change(data.points.length - 1)}>Zurück zu heute</button>}<span>Heute</span></div>
    <details className={styles.method}><summary>Wie werden historische Werte berechnet?</summary><p>{data.note}</p></details>
  </div>;
}
