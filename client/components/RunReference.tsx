"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { Card } from "@/components/ui";
import { de } from "@/lib/format";
import { runReferenceApi, type ReferenceSelection, type RunReference } from "@/lib/run-reference";

const eventName = "run-reference-updated";
const actionClass = "text-xs font-semibold text-accent underline underline-offset-4 disabled:opacity-50";
const dateLabel = (value: string) => `${value.slice(8, 10)}.${value.slice(5, 7)}.${value.slice(2, 4)}`;

function useRevision() {
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const refresh = () => setRevision(value => value + 1);
    const events = [eventName, "milon:data-refresh", "run-analysis-updated"];
    events.forEach(event => window.addEventListener(event, refresh));
    return () => events.forEach(event => window.removeEventListener(event, refresh));
  }, []);
  return [revision, () => setRevision(value => value + 1)] as const;
}

export function RunReferenceControl({ activityId }: { activityId: string }) {
  const [data, setData] = useState<ReferenceSelection | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, retry] = useRevision();
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError("");
    runReferenceApi.selection(activityId, controller.signal).then(value => {
      if (!controller.signal.aborted) setData(value);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [activityId, revision]);
  const selected = data?.reference?.activity_id === activityId;
  async function choose() {
    setBusy(true); setError("");
    try {
      setData(await runReferenceApi.choose(activityId));
      window.dispatchEvent(new Event(eventName));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Speichern fehlgeschlagen."); }
    finally { setBusy(false); }
  }
  return <div className="text-xs text-muted">
    {selected ? <Link href="/laufen#referenzrunde" scroll={false} className={actionClass}>Deine Referenzrunde →</Link>
      : data?.selectable ? <button type="button" onClick={choose} disabled={busy} className={actionClass}>{busy ? "Wird gespeichert …" : data.reference ? "Als neue Referenzrunde wählen" : "Als Referenzrunde wählen"}</button>
      : data ? <span>{data.reason}</span> : !error ? <span>Referenzrunde wird geprüft …</span> : null}
    {error && <p role="alert" className="mt-1">{error} <button type="button" onClick={retry} className={actionClass}>Erneut laden</button></p>}
  </div>;
}

function ReferenceChart({ data }: { data: RunReference }) {
  const ref = useRef<HTMLDivElement>(null), title = useId();
  const [width, setWidth] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  const values = data.observations.map(item => item.hr_delta_bpm);
  const low = Math.floor(Math.min(-2, ...values) / 2) * 2, high = Math.ceil(Math.max(2, ...values) / 2) * 2;
  const first = Date.parse(`${data.period_start}T00:00:00`), last = Date.parse(`${data.period_end}T23:59:59`);
  const x = (date: string) => 40 + (Date.parse(date) - first) / (last - first) * (width - 54);
  const y = (value: number) => 22 + (high - value) / (high - low) * 96;
  const anchorTime = Date.parse(data.reference!.started_at);
  return <div ref={ref} className="mt-4">
    <svg className="w-full overflow-visible" viewBox={`0 0 ${width} 150`} role="img" aria-labelledby={title}>
      <title id={title}>Pulsunterschied zur Referenz in Schlägen pro Minute. Einzelne Wiederholungen bei ähnlichem Tempo und Gefälle. Negative Werte bedeuten niedrigeren Puls, keinen nachgewiesenen Fitnessgewinn.</title>
      {[high, 0, low].map(value => <g key={value}><line x1="40" x2={width - 14} y1={y(value)} y2={y(value)} stroke="var(--color-line)" strokeDasharray={value === 0 ? undefined : "3 4"} /><text x="31" y={y(value) + 4} textAnchor="end" fontSize="11" fill="var(--color-muted)">{value > 0 ? "+" : ""}{de(value, 0)}</text></g>)}
      <text x="40" y="11" fontSize="10" fill="var(--color-muted)">Δ Puls · bpm</text>
      {anchorTime >= first && anchorTime <= last && <circle cx={x(data.reference!.started_at)} cy={y(0)} r="4" fill="var(--color-surface)" stroke="var(--color-muted)" strokeWidth="1.5"><title>Referenz · {dateLabel(data.reference!.started_at)}</title></circle>}
      {data.observations.map(item => <a key={item.activity_id} href={`/laufen/${item.activity_id}#vergleich`} aria-label={`Lauf vom ${dateLabel(item.started_at)}: ${de(item.hr_delta_bpm, 1)} bpm zur Referenz. Statistischen Streckenvergleich öffnen.`}>
        <circle cx={x(item.started_at)} cy={y(item.hr_delta_bpm)} r="10" fill="transparent" />
        <circle cx={x(item.started_at)} cy={y(item.hr_delta_bpm)} r="4" fill="var(--color-accent)"><title>{dateLabel(item.started_at)} · {item.hr_delta_bpm > 0 ? "+" : ""}{de(item.hr_delta_bpm, 1)} bpm · {item.matched_pairs} Minutenpaare · Pace {item.pace_delta_seconds > 0 ? "+" : ""}{de(item.pace_delta_seconds, 1)} s/km</title></circle>
      </a>)}
      <text x="40" y="143" fontSize="11" fill="var(--color-muted)">{dateLabel(data.period_start)}</text><text x={width - 14} y="143" textAnchor="end" fontSize="11" fill="var(--color-muted)">{dateLabel(data.period_end)}</text>
    </svg>
  </div>;
}

export function RunReferenceCard() {
  const [data, setData] = useState<RunReference | null>(null), [error, setError] = useState("");
  const [days, setDays] = useState(365), [busy, setBusy] = useState(false);
  const [revision, retry] = useRevision();
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    runReferenceApi.overview(days, controller.signal).then(value => {
      if (!controller.signal.aborted) setData(value);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [days, revision]);
  async function clear() {
    setBusy(true); setError("");
    try { await runReferenceApi.clear(); setData(null); window.dispatchEvent(new Event(eventName)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Änderung fehlgeschlagen."); }
    finally { setBusy(false); }
  }
  const latest = data?.observations.at(-1);
  return <section id="referenzrunde" className="mt-4 scroll-mt-20" aria-labelledby="reference-title"><Card>
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 id="reference-title" className="text-sm font-semibold">Deine Referenzrunde</h3><p className="mt-1 text-[11px] text-muted">Gleiche Runde · ähnliches Tempo · Puls im Verlauf</p></div>
      {data?.reference && <div className="flex gap-1" aria-label="Zeitraum der Referenzrunde">{[[90, "3M"], [180, "6M"], [365, "12M"]].map(([value, label]) => <button key={value} type="button" aria-pressed={days === value} onClick={() => setDays(Number(value))} className={`rounded px-2 py-1 text-xs ${days === value ? "bg-accent text-white" : "bg-bg text-muted"}`}>{label}</button>)}</div>}
    </div>
    {error ? <p role="alert" className="mt-3 text-xs text-muted">{error} <button onClick={retry} className={actionClass}>Erneut laden</button></p>
      : !data || data.days !== days ? <p role="status" className="mt-3 text-xs text-muted">Referenzrunde wird geladen …</p>
      : data.status === "unset" ? <p className="mt-3 text-xs text-muted">Öffne eine deiner <Link href="/laufen#strecken" scroll={false} className={actionClass}>Strecken</Link> und wähle sie als Referenzrunde. Passende Wiederholungen erscheinen hier automatisch.</p>
      : <>
        {data.reference && <p className="mt-3 text-xs"><Link href={`/laufen/${data.reference.activity_id}`} className="font-semibold text-accent">{data.reference.title} · {de(data.reference.distance_km, 1)} km</Link><span className="text-muted"> · Referenz vom {dateLabel(data.reference.started_at)}</span></p>}
        {data.status === "unavailable" ? <p className="mt-3 text-xs text-muted">{data.reason}</p>
          : !latest ? <p className="mt-3 text-xs text-muted">Noch keine passende Wiederholung im Zeitraum. Gleiche Richtung, ähnliche Strecke und Dauer sowie sechs vergleichbare Minuten sind erforderlich.</p>
          : <>
            <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1"><p className="font-display text-2xl font-extrabold tabular-nums">{latest.hr_delta_bpm > 0 ? "+" : ""}{de(latest.hr_delta_bpm, 1)} <span className="text-sm font-normal text-muted">bpm</span></p><p className="text-xs text-muted">Letzte Wiederholung · {dateLabel(latest.started_at)} · {latest.matched_pairs} Minutenpaare</p></div>
            <p className="mt-1 text-[11px] text-muted">Pace-Differenz {latest.pace_delta_seconds > 0 ? "+" : ""}{de(latest.pace_delta_seconds, 1)} s/km · {data.observations.length} passende Wiederholungen · Punkte öffnen den Vergleich</p>
            <ReferenceChart data={data} />
            <p className="mt-1 text-[11px] text-muted">Puls niedriger oder höher als in der Referenz; einzelne Beobachtungen, kein Fitnessurteil.</p>
          </>}
        <div className="mt-3 flex flex-wrap items-start justify-between gap-3 border-t border-line pt-3"><details className="min-w-0 flex-1 text-[11px] text-muted"><summary className="cursor-pointer">Vergleichsbasis{data.sensor_since ? ` · Sensorperiode seit ${dateLabel(data.sensor_since)}` : ""}</summary><p className="mt-2 leading-relaxed">{data.method}</p></details><button type="button" disabled={busy} onClick={clear} className={actionClass}>Referenz lösen</button></div>
      </>}
  </Card></section>;
}
