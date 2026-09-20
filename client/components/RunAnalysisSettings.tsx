"use client";

import { useEffect, useState } from "react";
import { api, type AnalysisRun, type RunningFitnessData, type RunningFitnessReferenceUpdate } from "@/lib/api";
import { de, dm } from "@/lib/format";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
const inputClass = "min-w-0 rounded border border-line bg-surface px-3 py-2 text-base sm:text-sm";
const buttonClass = "rounded border border-line px-3 py-2 text-xs disabled:opacity-40";

const CATEGORIES: [AnalysisRun["category"], string][] = [
  ["auto", "Automatisch"], ["normal", "Normaler Lauf"], ["beast", "Beast / Hindernislauf"],
  ["trail", "Trail"], ["run_walk", "Run-Walk"], ["measurement_error", "Messfehler"],
];

function RunEditor({ run, busy, onSave }: { run: AnalysisRun; busy: boolean; onSave: (run: AnalysisRun) => void }) {
  const [category, setCategory] = useState(run.category);
  const [exclude, setExclude] = useState(run.exclude);
  const changed = category !== run.category || exclude !== run.exclude;
  return <div className="grid gap-2 border-t border-line py-3 sm:grid-cols-[1fr_1fr_auto] sm:items-center">
    <p className="text-xs">{dm(run.date)} · {de(run.distance_km, 1)} km · {de(run.duration_min, 0)} min</p>
    <div className="min-w-0 space-y-2">
      <select aria-label={`Laufart am ${dm(run.date)}`} value={category} disabled={busy} onChange={(e) => setCategory(e.target.value as AnalysisRun["category"])} className="w-full rounded border border-line bg-surface px-2 py-1 text-base sm:text-sm">
        {CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={exclude} disabled={busy} onChange={(e) => setExclude(e.target.checked)} />Aus Fitnessanalyse ausschließen</label>
    </div>
    <button disabled={!changed || busy} onClick={() => onSave({ ...run, category, exclude })} className="rounded border border-line px-3 py-2 text-xs disabled:opacity-40">Speichern</button>
  </div>;
}

export function RunAnalysisSettings() {
  const [open, setOpen] = useState(false);
  return <div className="mt-3 text-right"><button className="text-xs text-muted underline underline-offset-4" onClick={() => setOpen(true)}>Laufanalyse einstellen</button>{open && <RunAnalysisDialog title="Laufanalyse einstellen" onClose={() => setOpen(false)}><SettingsContent /></RunAnalysisDialog>}</div>;
}

function SettingsContent() {
  const [data, setData] = useState<RunningFitnessData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [rest, setRest] = useState("");
  const [source, setSource] = useState("");
  const [sensorDate, setSensorDate] = useState("");
  const [sensorLabel, setSensorLabel] = useState("");
  const [sessions, setSessions] = useState<AnalysisRun[] | null>(null);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => { void api.runFitness().then(setData).catch((e) => setError(String(e))); void loadSessions(); }, []);
  async function save(body: RunningFitnessReferenceUpdate) {
    setBusy(true); setSaveError(null);
    try { setData(await api.runFitnessReference(body)); window.dispatchEvent(new Event("run-analysis-updated")); return true; }
    catch (e) { setSaveError(`Speichern fehlgeschlagen: ${String(e)}`); return false; }
    finally { setBusy(false); }
  }
  async function loadSessions() {
    setSessionsLoading(true);
    setSessionsError(null);
    try { setSessions(await api.runAnalysisSessions()); }
    catch (e) { setSessionsError(String(e)); }
    finally { setSessionsLoading(false); }
  }
  async function saveRun(run: AnalysisRun) {
    setSaving(true);
    setSessionsError(null);
    try {
      const saved = await api.runAnalysisUpdate(run.external_id, { category: run.category, exclude: run.exclude });
      setSessions((rows) => rows?.map((row) => row.external_id === saved.external_id ? saved : row) ?? null);
      window.dispatchEvent(new Event("run-analysis-updated"));
    } catch (e) { setSessionsError(`Speichern fehlgeschlagen: ${String(e)}`); }
    finally { setSaving(false); }
  }

  const calibration = data?.calibration;
  const candidate = calibration?.candidate?.candidate_bpm;
  return <div className="text-xs">
    {error && <p role="alert">Referenzen konnten nicht geladen werden: {error}</p>}
    {!data && !error && <p role="status">Referenzen werden geladen …</p>}
      {calibration && <section><h3 className="font-semibold">Pulsreferenzen & Sensorwechsel</h3>
        <p className="mt-3">Hohe Belastungsreferenz: <strong>{de(calibration.max_hr, 0)} bpm</strong> · {calibration.high_hr_source}</p>
        <p className="mt-1 text-muted">Wiederholt beobachteter hoher Puls, keine gesicherte HFmax. Ruhepuls: {de(calibration.rest_hr, 0)} bpm · {calibration.rest_source}. Referenzversion {calibration.revision}.</p>
        {candidate != null && (calibration.max_hr == null || candidate > calibration.max_hr) && <div className="mt-3"><p>{calibration.candidate?.reason}</p><button disabled={busy} className={`${buttonClass} mt-2`} onClick={() => void save({ max_hr: candidate })}>{de(candidate, 0)} bpm als neue Belastungsreferenz übernehmen</button></div>}
        <p className="mt-3 text-muted">Neue Referenzen berechnen die gesamte Historie einheitlich neu. Für den Ruhepuls mehrere vergleichbare Messungen im wachen Ruhezustand verwenden und ihre Herkunft dokumentieren.</p>
        <form className="mt-3 grid gap-2 sm:grid-cols-[7rem_1fr_auto]" onSubmit={(e) => { e.preventDefault(); void save({ rest_hr: Number(rest), rest_source: source.trim() }); }}>
          <input className={inputClass} type="number" min="25" max="120" step="1" required value={rest} onChange={(e) => setRest(e.target.value)} placeholder="bpm" aria-label="Gemessener Ruhepuls in bpm" disabled={busy} />
          <input className={inputClass} required maxLength={300} value={source} onChange={(e) => setSource(e.target.value)} placeholder="Messbedingungen, Datum und Anzahl" aria-label="Herkunft der Ruhepulsreferenz" disabled={busy} />
          <button className={buttonClass} disabled={busy || !source.trim()} type="submit">Ruhepuls speichern</button>
        </form>
        <p className="mt-5 font-semibold">Neuer Brustgurt oder neue Uhr</p><p className="mt-1 text-muted">Das Datum trennt Auswertungsfenster und Linien, damit unterschiedliche Sensoren nicht unbemerkt vermischt werden.</p>
        <form className="mt-3 grid gap-2 sm:grid-cols-[10rem_1fr_auto]" onSubmit={(e) => { e.preventDefault(); void save({ sensor_change: { date: sensorDate, label: sensorLabel.trim() } }).then((saved) => { if (saved) { setSensorDate(""); setSensorLabel(""); } }); }}>
          <input className={inputClass} type="date" required value={sensorDate} onChange={(e) => setSensorDate(e.target.value)} aria-label="Datum des Sensorwechsels" disabled={busy} />
          <input className={inputClass} required maxLength={100} value={sensorLabel} onChange={(e) => setSensorLabel(e.target.value)} placeholder="Bezeichnung des Sensors" aria-label="Neuer Sensor" disabled={busy} />
          <button className={buttonClass} disabled={busy || !sensorLabel.trim()} type="submit">Wechsel speichern</button>
        </form>
        {calibration.sensor_changes.length > 0 && <ul className="mt-3 space-y-1">{calibration.sensor_changes.map((s) => <li key={`${s.date}:${s.label}`}>{dm(s.date)} · {s.label}</li>)}</ul>}
        {busy && <p className="mt-3 text-muted" role="status">Referenz wird gespeichert und die Historie neu berechnet …</p>}
        {saveError && <p className="mt-3 break-words text-bad" role="alert">{saveError}</p>}
      </section>}
<section className="mt-6 border-t border-line pt-4"><h3 className="font-semibold">Läufe einordnen & ausschließen</h3>
      <p className="my-2 text-muted">Sonderläufe bleiben in Historie und Trainingsmenge erhalten. Beast, Trail, Run-Walk und Messfehler werden aus dieser Fitnessanalyse ausgeschlossen.</p>
      {sessionsLoading && <p role="status">Läufe werden geladen …</p>}
      {sessionsError && <p className="my-2 break-words text-bad" role="alert">{sessionsError} <button className="underline" onClick={() => void loadSessions()}>Neu laden</button></p>}
      {saving && <p role="status">Gespeichert wird; danach wird die Analyse aktualisiert …</p>}
      {sessions?.length === 0 && <p>Keine Läufe verfügbar.</p>}
      <div className="max-h-96 overflow-y-auto">{sessions?.map((run) => <RunEditor key={`${run.external_id}:${run.category}:${run.exclude}`} run={run} busy={saving} onSave={(row) => void saveRun(row)} />)}</div>
    </section>
  </div>;
}
