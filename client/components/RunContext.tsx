"use client";

import { useEffect, useRef, useState } from "react";
import { de } from "@/lib/format";
import { intentReadout, runContextApi, type RunContextData, type RunIntent, type RunWeather } from "@/lib/run-context";

const choices: [RunIntent, string][] = [["easy", "Locker"], ["long", "Lang"], ["tempo", "Tempo"]];
const efforts = ["Sehr leicht", "Leicht", "Mittel", "Anstrengend", "Sehr anstrengend"];
const chip = "rounded-card border px-3 py-1.5 text-xs transition-colors disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-accent";

export function WeatherReadout({ weather }: { weather: RunWeather }) {
  if (!weather.available) return <span className="text-muted">Wetter {weather.status === "never" ? "noch nicht importiert" : weather.status === "error" ? "gerade nicht abrufbar" : "nicht verfügbar"}</span>;
  const direction = weather.wind_from_degrees == null ? null : ["N", "NO", "O", "SO", "S", "SW", "W", "NW"][Math.round(weather.wind_from_degrees / 45) % 8];
  const time = weather.observed_at ? new Date(weather.observed_at).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" }) : null;
  return <span>
    <span className="font-medium text-ink">{weather.temperature_c != null ? `${de(weather.temperature_c, 1)} °C` : "Temperatur unbekannt"}</span>
    {weather.humidity_pct != null && ` · ${de(weather.humidity_pct, 0)} % Feuchte`}{direction && ` · Wind aus ${direction}`}
    <span className="block text-muted">Garmin · Wetterstation{time ? ` · ${time}` : " · Messzeit unbekannt"}{!weather.time_aligned && time ? " · zeitlich nicht passend" : ""}{weather.status !== "available" ? " · letzter verfügbarer Stand" : ""}</span>
  </span>;
}

export function RunContext({ activityId }: { activityId: string }) {
  const [data, setData] = useState<RunContextData | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0), [saved, setSaved] = useState(false);
  const saving = useRef(false), generation = useRef(0);
  useEffect(() => {
    const refresh = () => { if (!saving.current) setRevision(value => value + 1); };
    window.addEventListener("milon:data-refresh", refresh);
    const controller = new AbortController(), version = ++generation.current;
    runContextApi.get(activityId, controller.signal).then(value => {
      if (!controller.signal.aborted && version === generation.current) { setData(value); setError(""); }
    }).catch(reason => { if (!controller.signal.aborted && version === generation.current) setError(reason.message); });
    return () => { controller.abort(); window.removeEventListener("milon:data-refresh", refresh); };
  }, [activityId, revision]);
  useEffect(() => { if (!saved) return; const timer = window.setTimeout(() => setSaved(false), 2000); return () => window.clearTimeout(timer); }, [saved]);
  async function update(fields: { intent?: RunIntent | null; training_effort?: number | null }) {
    if (saving.current) return;
    saving.current = true; ++generation.current; setBusy(true); setError("");
    try { setData(await runContextApi.update(activityId, fields)); setSaved(true); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Speichern fehlgeschlagen."); }
    finally { saving.current = false; setBusy(false); }
  }
  return <section aria-label="Laufabsicht und Empfinden" className="mb-4 rounded-card border border-line bg-surface px-4 py-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-2"><span className="mr-2 text-xs font-semibold">Dein Laufziel</span>
        {choices.map(([value, label]) => <button key={value} type="button" disabled={!data || busy} aria-pressed={data?.intent === value} className={`${chip} ${data?.intent === value ? "border-accent/30 bg-accent/10 text-accent" : "border-line text-muted hover:border-accent"}`} onClick={() => void update({ intent: data?.intent === value ? null : value })}>{label}</button>)}
        <span className="hidden text-[10px] text-muted sm:inline">optional</span>
      </div>
      <span className="text-[10px] text-accent" role="status">{busy ? "Speichert …" : saved ? "Gespeichert ✓" : ""}</span>
    </div>
    {data && (data.intent || data.training_effort != null) && <div className="mt-3 flex flex-wrap items-center gap-2"><span className="mr-2 text-xs text-muted">Wie anstrengend?</span>
      {data.effort_editable ? <><select aria-label="Anstrengung dieses Laufs" value={data.training_effort ?? ""} disabled={busy} onChange={event => void update({ training_effort: event.target.value ? Number(event.target.value) : null })} className="min-w-0 max-w-full rounded-card border border-line bg-surface px-2 py-1.5 text-base sm:hidden"><option value="">Nicht angegeben</option>{efforts.map((label, index) => <option key={label} value={index + 1}>{label}</option>)}</select>{efforts.map((label, index) => <button key={label} type="button" disabled={busy} aria-pressed={data.training_effort === index + 1} className={`${chip} hidden sm:inline-block ${data.training_effort === index + 1 ? "border-accent/30 bg-accent/10 text-accent" : "border-line text-muted hover:border-accent"}`} onClick={() => void update({ training_effort: data.training_effort === index + 1 ? null : index + 1 })}>{label}</button>)}</>
        : <span className="text-xs text-muted">{data.effort_conflict ? "Der Tages-Check-in ist bereits anderweitig belegt." : "Anstrengung nach vollständiger Laufzuordnung verfügbar."}</span>}
    </div>}
    {data && <p className="mt-2 text-xs leading-relaxed text-muted">{intentReadout(data.intent, data.training_effort)}</p>}
    {error && <p className="mt-2 text-xs text-bad" role="alert">{error} {!data && <button className="underline" onClick={() => setRevision(value => value + 1)}>Erneut laden</button>}</p>}
    {data?.weather.available && <div className="mt-3 border-t border-line pt-2 text-[11px] leading-relaxed"><WeatherReadout weather={data.weather} /></div>}
  </section>;
}

export function ComparisonWeather({ first, second }: { first: string; second: string }) {
  const [data, setData] = useState<{ first: RunWeather; second: RunWeather } | null>(null), [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setFailed(false);
    Promise.all([runContextApi.get(first, controller.signal), runContextApi.get(second, controller.signal)]).then(([a, b]) => {
      if (!controller.signal.aborted) setData({ first: a.weather, second: b.weather });
    }).catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [first, second]);
  if (failed) return <p className="mt-3 text-xs text-muted">Wettervergleich konnte nicht geladen werden.</p>;
  if (!data) return null;
  return <div className="mt-3 border-t border-line pt-3 text-[11px] leading-relaxed">
    <div className="grid gap-3 sm:grid-cols-2"><div><p className="mb-1 font-semibold">Ausgewählter Lauf</p><WeatherReadout weather={data.first} /></div><div><p className="mb-1 font-semibold">Vergleichslauf</p><WeatherReadout weather={data.second} /></div></div>
    <p className="mt-2 text-muted">Stationswetter als Kontext. Bedingungen entlang der Strecke können abweichen; Puls und Pace werden nicht wetterbereinigt.</p>
  </div>;
}
