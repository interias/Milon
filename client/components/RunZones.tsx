"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui";
import { de } from "@/lib/format";
import styles from "./RunZones.module.css";

type Zone = {
  zone: number; label: string; pct_low: number; pct_high: number; hr_low: number; hr_high: number;
  pace_fast_seconds: number | null; pace_median_seconds: number | null; pace_slow_seconds: number | null;
  speed_low_kmh: number | null; speed_median_kmh: number | null; speed_high_kmh: number | null;
  supporting_runs: number; minutes: number; coverage: number | null; source: "current" | "historical" | null;
  source_label: string | null; status: string; from_date: string | null; to_date: string | null;
};
type Zones = {
  hr_max: number | null; runs: number; minutes: number; from_date: string; to_date: string;
  sensor: { label: string; since: string | null }; zones: Zone[]; pace_status: string; pace_reason: string;
  caveat: string; schema_source: string;
};
const BASE = process.env.NEXT_PUBLIC_API_URL || "/api";
const COLORS = ["#3978bb", "#208568", "#b38108", "#d26528", "#bb3c4e"];
type TempoUnit = "pace" | "speed";

async function load() {
  const response = await fetch(`${BASE}/metrics/running/zones`, { cache: "no-store" });
  if (!response.ok) throw new Error("Pulszonen konnten nicht geladen werden.");
  return response.json() as Promise<Zones>;
}

function pace(seconds: number) {
  const rounded = Math.round(seconds);
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}`;
}
function shortDate(day: string | null) { return day ? `${day.slice(8, 10)}.${day.slice(5, 7)}.` : ""; }

function ZoneField({ zones, unit, onUnitChange }: { zones: Zone[]; unit: TempoUnit; onUnitChange: (unit: TempoUnit) => void }) {
  const format = (value: number) => unit === "pace" ? pace(value) : de(value, 1);
  const unitLabel = unit === "pace" ? "min/km" : "km/h";
  const entries = zones.map((zone) => ({
    zone,
    median: unit === "pace" ? zone.pace_median_seconds : zone.speed_median_kmh,
    low: unit === "pace" ? zone.pace_fast_seconds : zone.speed_low_kmh,
    high: unit === "pace" ? zone.pace_slow_seconds : zone.speed_high_kmh,
  }));
  const values = entries.flatMap(({ low, median, high }) => [low, median, high])
    .filter((value): value is number => value !== null && Number.isFinite(value) && value > 0);
  const minimum = values.length ? Math.min(...values) : 0;
  const maximum = values.length ? Math.max(...values) : 0;
  const baseStep = unit === "pace" ? 60 : 1;
  const step = Math.max(baseStep, Math.ceil((maximum - minimum) / (4 * baseStep)) * baseStep);
  const lower = Math.max(0, Math.floor(minimum / step) * step - step / 4);
  const upper = Math.ceil(maximum / step) * step + step / 4;
  const position = (value: number) => 8 + 108 * (unit === "pace" ? value - lower : upper - value) / (upper - lower);
  const ticks: number[] = [];
  if (values.length) for (let tick = Math.ceil(lower / step) * step; tick <= upper; tick += step) ticks.push(tick);
  const zoneStyle = (zone: Zone) => ({ "--zone": COLORS[zone.zone - 1] }) as CSSProperties;

  return <figure className={styles.field}>
    <figcaption className="sr-only">Tempo je Pulszone. Offene Ringe zeigen die Enden der beobachteten Spanne P10–P90, der dunkle Punkt den Median. Schnellere Tempi stehen oben.</figcaption>
    <div className={styles.caption}>
      <div className={styles.units} aria-label="Tempo-Einheit">
        <button type="button" aria-pressed={unit === "pace"} onClick={() => onUnitChange("pace")}>min/km</button>
        <span aria-hidden="true">/</span>
        <button type="button" aria-pressed={unit === "speed"} onClick={() => onUnitChange("speed")}>km/h</button>
        <span aria-hidden="true">↑</span>
      </div>
      <div className={styles.legend}><span><i className={styles.keyDot} />Median</span><span><i className={styles.keyRange} />P10–P90</span></div>
    </div>
    <div className={styles.plot} aria-hidden="true">
      <div className={styles.axis}>{ticks.map((value) => <span key={value} style={{ top: position(value) }}>{format(value)}</span>)}</div>
      <div className={styles.plotArea}>
        <div className={styles.lanes}>{entries.map(({ zone, low, median, high }) => {
          const hasRange = low !== null && high !== null;
          const top = hasRange ? Math.min(position(low), position(high)) : 0;
          const bottom = hasRange ? Math.max(position(low), position(high)) : 0;
          return <div key={zone.zone} className={styles.lane} style={zoneStyle(zone)}>
            {hasRange && <span className={styles.range} style={{ top, height: bottom - top }} />}
            {median !== null && <span className={styles.marker} style={{ top: position(median) }} />}
          </div>;
        })}</div>
        {ticks.map((value) => <span key={value} className={styles.gridline} style={{ top: position(value) }} />)}
        {!values.length && <p className={styles.empty}>Noch keine Tempo-Daten</p>}
      </div>
    </div>
    <div className={styles.footer}>
      <div className={styles.footerAxis}><span>Median</span><span>bpm</span><span>Spanne</span></div>
      <div className={styles.footerGrid}>{entries.map(({ zone, low, median, high }) => <div key={zone.zone} className={styles.values} style={zoneStyle(zone)}>
        <span className={`${styles.median} ${median === null ? styles.missing : ""}`} aria-label={`Z${zone.zone} Median: ${median === null ? "keine Daten" : `${format(median)} ${unitLabel}`}`}>{median === null ? "—" : format(median)}</span>
        <span className={styles.zone} title={zone.label}>Z{zone.zone}{zone.source === "historical" && <sup>†</sup>}</span>
        <span className={styles.heartRate} aria-label={`${zone.hr_low} bis ${zone.hr_high} bpm`}>{zone.hr_low}–<span>{zone.hr_high}</span></span>
        {low !== null && high !== null ? <span className={styles.bounds} aria-label={`Spanne ${format(low)} bis ${format(high)} ${unitLabel}`}><span>{format(low)}</span><span>{format(high)}</span></span>
          : <span className={styles.noRange} aria-label="Keine beobachtete Spanne">—</span>}
      </div>)}</div>
    </div>
  </figure>;
}

export function RunZones() {
  const [data, setData] = useState<Zones | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [maxHr, setMaxHr] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [unit, setUnit] = useState<TempoUnit>("pace");
  const requestRevision = useRef(0);
  const reload = useCallback(async () => {
    const revision = ++requestRevision.current;
    try {
      const result = await load();
      if (revision !== requestRevision.current) return false;
      setData(result); setError(null);
      return true;
    } catch (err) {
      if (revision === requestRevision.current) throw err;
      return false;
    }
  }, []);
  useEffect(() => {
    let active = true;
    async function update() {
      try { await reload(); }
      catch (err) { if (active) setError(err instanceof Error ? err.message : String(err)); }
    }
    function onVisible() { if (document.visibilityState === "visible") void update(); }
    void update();
    const timer = window.setInterval(onVisible, 60_000);
    window.addEventListener("focus", onVisible);
    window.addEventListener("milon:data-refresh", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => { active = false; requestRevision.current++; window.clearInterval(timer); window.removeEventListener("focus", onVisible);
      window.removeEventListener("milon:data-refresh", onVisible); document.removeEventListener("visibilitychange", onVisible); };
  }, [reload]);

  async function refresh() {
    setError(null); setFeedback(null); setRefreshing(true);
    try { if (await reload()) setFeedback("Ansicht aktualisiert."); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setRefreshing(false); }
  }
  async function save() {
    const value = Number(maxHr);
    if (!Number.isInteger(value) || value < 100 || value > 250) { setError("Bitte einen HFmax-Referenzwert zwischen 100 und 250 bpm eingeben."); return; }
    setBusy(true); setError(null); setFeedback(null); requestRevision.current++;
    try {
      await api.settingsUpdate({ run_hr_max: value });
      await reload(); setEditing(false); setFeedback("HFmax-Referenzwert gespeichert.");
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  }

  const historical = data?.zones.filter((zone) => zone.source === "historical") ?? [];

  return <Card className="max-w-[440px]">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <h3 className="text-sm font-semibold">Pulszonen & dein Tempo</h3>
      {data && <button type="button" title="HFmax-Referenzwert ändern" aria-label="HFmax-Referenzwert ändern" aria-expanded={editing} aria-controls="run-zones-edit" onClick={() => { setMaxHr(data.hr_max ? String(data.hr_max) : ""); setEditing(!editing); setFeedback(null); }} className="flex items-center gap-1 py-0.5 text-[11px] font-medium text-accent hover:underline">
        HFmax {data.hr_max ? de(data.hr_max, 0) : "eintragen"}
        <svg aria-hidden="true" viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m16 3 5 5L8 21H3v-5L16 3Z" /><path d="m14 5 5 5" /></svg>
      </button>}
    </div>
    {!data && !error && <p className="mt-3 text-xs text-muted">Pulszonen werden geladen …</p>}
    {editing && <form id="run-zones-edit" className="mt-3 rounded-lg bg-surface-alt p-3" onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <label htmlFor="run-zones-hr-max" className="text-xs font-medium">HFmax-Referenzwert (bpm)</label>
      <div className="mt-1 flex flex-wrap gap-2"><input id="run-zones-hr-max" type="number" inputMode="numeric" min={100} max={250} step={1} value={maxHr}
        onChange={(event) => setMaxHr(event.target.value)} disabled={busy} className="w-24 rounded-lg border border-line bg-surface px-3 py-2 text-base sm:text-sm" />
        <button type="submit" disabled={busy} className="rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{busy ? "speichert …" : "Speichern"}</button>
        <button type="button" disabled={busy} onClick={() => setEditing(false)} className="px-2 py-2 text-xs text-muted">Abbrechen</button></div>
      <p className="mt-2 text-[11px] text-muted">Ein beobachteter Höchstpuls, auch mit Pulsgurt, bestätigt die tatsächliche physiologische HFmax nicht.</p>
    </form>}
    {data && <>
      {!!data.zones.length && <ZoneField zones={data.zones} unit={unit} onUnitChange={setUnit} />}
      {historical.map((zone) => <p key={zone.zone} className="mt-2 text-[10px] text-muted">† Z{zone.zone}: {zone.source_label} · {shortDate(zone.from_date)}–{shortDate(zone.to_date)}</p>)}
      {!data.zones.length && <p className="mt-3 text-xs text-muted">Bitte einen bekannten HFmax-Referenzwert eintragen. Die App leitet ihn nicht aus Pulsspitzen ab.</p>}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2 text-[10px] text-muted"><span>{data.runs > 0 ? `${data.sensor.label} · ${data.runs} Läufe` : historical.length ? "Historische Laufdaten" : `${data.sensor.label} · keine aktuellen Läufe`} · vorläufig</span>
        <button type="button" disabled={refreshing || busy} onClick={() => void refresh()} className="text-accent hover:underline disabled:opacity-50">{refreshing ? "lädt …" : "Aktualisieren"}</button></div>
      {data.pace_status === "insufficient" && <p className="mt-1 text-[11px] text-muted">{data.pace_reason}</p>}
      <details className="mt-2 text-[11px] text-muted"><summary className="cursor-pointer">Methode & Datenquellen</summary>
        <p className="mt-2">{data.caveat}</p>
        <p className="mt-2">Aktuelles Fenster: {shortDate(data.from_date)}–{shortDate(data.to_date)} · maximal 8 Wochen.</p>
        <ul className="mt-2 space-y-1">{data.zones.map((zone) => <li key={zone.zone}>Z{zone.zone} · {zone.label}: {zone.pace_median_seconds === null ? "Keine passenden Laufdaten" : `${zone.source_label} · ${zone.supporting_runs === 1 ? "ein Lauf" : `${zone.supporting_runs} Läufe`} · ${zone.minutes} Minuten · ${de((zone.coverage ?? 0) * 100, 0)} % Messabdeckung`}</li>)}</ul>
        <p className="mt-2">Je Lauf mindestens drei geeignete Minuten in der Zone. Aktuelle Garmin-Daten haben Vorrang, auch bei einem einzelnen Lauf. Fehlen passende aktuelle Minuten, wird die letzte 8-Wochen-Phase vor dem Uhrenwechsel separat als historische Quelle beschriftet. Es gibt keine Extrapolation in unbeobachtete Zonen.</p>
        <p className="mt-2">Schema: 50–60, 60–70, 70–80, 80–90 und 90–100 %. Gemeinsame Grenzen zählen zur höheren Zone. Dieses Schema kann von deinen Garmin-Einstellungen und der älteren Vier-Zonen-Trendanalyse abweichen. <a href={data.schema_source} target="_blank" rel="noreferrer" className="text-accent underline">Garmin-Zonenschema</a></p>
        <p className="mt-2">Neue importierte Läufe verändern die Korridore automatisch. Die Ansicht aktualisiert sich beim Öffnen, bei Rückkehr zur App und jede Minute.</p>
      </details>
    </>}
    {error && <p role="alert" className="mt-3 text-xs text-bad">{error}</p>}
    {feedback && <p role="status" className="mt-3 text-xs text-accent">{feedback}</p>}
  </Card>;
}
