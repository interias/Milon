"use client";

import { useEffect, useRef, useState } from "react";
import { Card } from "./ui";
import { coachActionsApi, type CoachAction, type CoachActionMetric, type CoachActionsData, type CoachActionStatus } from "@/lib/coach-actions";

const dateLabel = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
const numberLabel = (value: number | null, metric: CoachActionMetric) => value == null ? "–" : value.toLocaleString("de-DE", { maximumFractionDigits: metric === "steps" ? 0 : 1 });
const field = "w-full rounded-lg border border-line bg-surface-alt px-3 py-2 text-base focus:border-accent focus:outline-none sm:text-sm";
const button = "rounded border border-line px-3 py-2 text-xs hover:border-accent disabled:opacity-50";
const feedbackLabels: [CoachActionStatus, string][] = [["implemented", "Umgesetzt"], ["partly", "Teilweise"], ["not_tried", "Nicht ausprobiert"]];

function ActionEntry({ entry, onChange, onRemove, onMutation }: {
  entry: CoachAction; onChange: (entry: CoachAction) => void; onRemove: (id: number) => void;
  onMutation: (started: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState(entry.note ?? "");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [saved, setSaved] = useState(false);
  const comparison = entry.comparison;

  async function feedback(values: { status?: CoachActionStatus; note?: string | null }) {
    onMutation(true);
    setBusy(true); setError(null); setSaved(false);
    try { onChange(await coachActionsApi.feedback(entry.id, values)); setSaved(true); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); onMutation(false); }
  }

  async function remove() {
    onMutation(true);
    setBusy(true); setError(null);
    try { await coachActionsApi.remove(entry.id); onRemove(entry.id); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); onMutation(false); }
  }

  return <article className="min-w-0">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <p className="min-w-0 flex-1 break-words text-sm font-semibold">{entry.action}</p>
      <span className="rounded bg-accent/8 px-2 py-1 text-[11px] text-accent">{entry.phase === "running" ? "Läuft" : "Rückblick"}</span>
    </div>
    <p className="mt-1 text-xs text-muted">{dateLabel(entry.starts_on)}–{dateLabel(entry.ends_on)} · 7 Tage{entry.source_report_id != null ? " · aus dem Coach-Bericht übernommen" : ""}</p>
    {comparison && <div className="mt-3 rounded border border-line bg-surface-alt p-3">
      <p className="text-xs font-semibold">{comparison.label} <span className="font-normal text-muted">· Tagesmittel {comparison.unit === "/Tag" ? "pro Tag" : comparison.unit}</span></p>
      <div className="mt-2 grid grid-cols-3 gap-3 tabular-nums">
        {([["Davor", comparison.before], ["Im Zeitraum", comparison.during]] as const).map(([label, window]) => <div key={label}>
          <p className="text-[11px] text-muted">{label}</p>
          <p className="mt-0.5 font-display text-lg font-bold">{numberLabel(window.mean, comparison.metric)}</p>
          <p className="text-[10px] text-muted">{window.days ? `${window.recorded_days}/${window.days} Tage` : "0 Messtage"}</p>
          <p className="mt-0.5 text-[10px] text-muted">{window.end ? `${dateLabel(window.start)}–${dateLabel(window.end)}` : "Ab morgen sichtbar"}</p>
        </div>)}
        <div>
          <p className="text-[11px] text-muted">Unterschied</p>
          <p className="mt-0.5 font-display text-lg font-bold">{comparison.delta != null && comparison.delta > 0 ? "+" : ""}{numberLabel(comparison.delta, comparison.metric)}</p>
          {comparison.metric === "energy" && <p className="text-[10px] text-muted">Punkte</p>}
          <p className="text-[10px] text-muted">{entry.phase === "running" ? "Zwischenstand" : "Zeitraum beendet"}</p>
        </div>
      </div>
      <p className="mt-2 text-[11px] text-muted">{comparison.reason}</p>
      <details className="mt-1 text-[11px] text-muted"><summary className="cursor-pointer">Berechnung & Datenbasis</summary><p className="mt-1">{comparison.method} {comparison.note}</p></details>
    </div>}
    <div className="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="Rückmeldung zur Wochenmaßnahme">
      {feedbackLabels.map(([status, label]) => <button key={status} type="button" disabled={busy}
        aria-pressed={entry.status === status} onClick={() => void feedback({ status: entry.status === status ? "pending" : status })}
        className={`${button} ${entry.status === status ? "border-accent bg-accent/8 text-accent" : ""}`}>{label}</button>)}
      <span role="status" className="text-[11px] text-muted">{busy ? "Speichert …" : saved ? "Gespeichert" : entry.status === "pending" ? "Freiwillig" : ""}</span>
    </div>
    <details className="mt-3 text-xs text-muted">
      <summary className="cursor-pointer">Notiz & Eintrag verwalten{entry.note ? " · Notiz vorhanden" : ""}</summary>
      <form className="mt-2 flex flex-wrap items-start gap-2" onSubmit={(event) => { event.preventDefault(); void feedback({ note: note.trim() || null }); }}>
        <label className="min-w-0 flex-1 basis-48"><span className="sr-only">Notiz zur Maßnahme</span><textarea rows={2} maxLength={300} className={field} value={note} onChange={(event) => { setNote(event.target.value); setSaved(false); }} placeholder="Was hat geholfen oder gefehlt?" /></label>
        <button type="submit" disabled={busy || note.trim() === (entry.note ?? "")} className={button}>Notiz speichern</button>
      </form>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {confirmRemove ? <><span>Eintrag wirklich entfernen?</span><button type="button" disabled={busy} onClick={() => void remove()} className={`${button} text-bad`}>Ja, entfernen</button><button type="button" disabled={busy} onClick={() => setConfirmRemove(false)} className={button}>Abbrechen</button></>
          : <button type="button" disabled={busy} onClick={() => setConfirmRemove(true)} className="py-1 text-muted underline">Eintrag entfernen</button>}
      </div>
    </details>
    {error && <p role="alert" className="mt-2 text-xs text-bad">{error}</p>}
  </article>;
}

export function CoachActions({ reportId }: { reportId: number | null }) {
  const [data, setData] = useState<CoachActionsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [action, setAction] = useState("");
  const [metric, setMetric] = useState<CoachActionMetric | "">("");
  const [sourceReport, setSourceReport] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const pendingMutations = useRef(0);
  const readController = useRef<AbortController | null>(null);
  useEffect(() => { setSourceReport(null); }, [reportId]);
  useEffect(() => {
    const refresh = () => setRevision((value) => value + 1);
    const onVisible = () => { if (document.visibilityState === "visible") refresh(); };
    window.addEventListener("milon:data-refresh", refresh);
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    // The server decides the local date, including a day change while this page stays open.
    const timer = window.setInterval(onVisible, 60_000);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("milon:data-refresh", refresh);
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);
  useEffect(() => {
    if (pendingMutations.current) return;
    const controller = new AbortController();
    readController.current = controller;
    coachActionsApi.list(controller.signal).then((next) => {
      if (!controller.signal.aborted && !pendingMutations.current) { setData(next); setLoadError(null); }
    }).catch((cause) => {
      if (!controller.signal.aborted) setLoadError(cause instanceof Error ? cause.message : String(cause));
    });
    return () => controller.abort();
  }, [revision]);

  function mutation(started: boolean) {
    if (started) {
      pendingMutations.current += 1;
      readController.current?.abort();
    } else {
      pendingMutations.current -= 1;
      if (!pendingMutations.current) setRevision((value) => value + 1);
    }
  }

  async function accept() {
    if (!action.trim() || busy) return;
    mutation(true);
    setBusy(true); setError(null);
    try {
      const entry = await coachActionsApi.accept(action.trim(), metric || null, sourceReport);
      setData((previous) => previous ? { ...previous, entries: [entry, ...previous.entries] } : previous);
      setEditing(false); setAction(""); setMetric("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); mutation(false); }
  }

  const active = data?.entries.find((entry) => entry.phase === "running");
  const displayedError = error ?? loadError;
  const latest = active ?? data?.entries[0];
  const history = data?.entries.filter((entry) => entry.id !== latest?.id) ?? [];
  const replace = (entry: CoachAction) => setData((previous) => previous ? { ...previous, entries: previous.entries.map((old) => old.id === entry.id ? entry : old) } : previous);
  const remove = (id: number) => setData((previous) => previous ? { ...previous, entries: previous.entries.filter((old) => old.id !== id) } : previous);

  return <Card className="mt-4">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-sm font-semibold">Meine Wochenmaßnahme</h3>
      {data && !active && !editing && <button type="button" onClick={() => { setSourceReport(null); setEditing(true); }} className={button}>Eine Maßnahme festhalten</button>}
    </div>
    {!data && !displayedError && <p role="status" className="text-xs text-muted">Lädt …</p>}
    {editing && <form onSubmit={(event) => { event.preventDefault(); void accept(); }} className="mb-4 space-y-3">
      <label className="block text-xs font-medium">Was möchtest du sieben Tage lang ausprobieren?
        <textarea autoFocus rows={2} maxLength={280} value={action} onChange={(event) => setAction(event.target.value)} required
          placeholder="Zum Beispiel: An Arbeitstagen nach dem Mittagessen spazieren gehen." className={`${field} mt-1`} />
      </label>
      <label className="block text-xs font-medium">Welchen Wert möchtest du dabei beobachten?
        <select value={metric} onChange={(event) => setMetric(event.target.value as CoachActionMetric | "")} className={`${field} mt-1`}>
          <option value="">Nur meine Rückmeldung</option>{data?.metrics.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
        </select>
      </label>
      {reportId != null && <label className="flex items-center gap-2 text-xs text-muted"><input type="checkbox" checked={sourceReport != null} onChange={(event) => setSourceReport(event.target.checked ? reportId : null)} />Mit dem angezeigten Coach-Bericht verknüpfen</label>}
      <p className="text-[11px] text-muted">Start heute · sieben Tage · du entscheidest, welche Empfehlung du übernimmst.</p>
      <div className="flex gap-2"><button type="submit" disabled={busy || !action.trim()} className="rounded bg-accent px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{busy ? "Speichert …" : "Maßnahme übernehmen"}</button><button type="button" disabled={busy} onClick={() => setEditing(false)} className={button}>Abbrechen</button></div>
    </form>}
    {latest ? <ActionEntry key={latest.id} entry={latest} onChange={replace} onRemove={remove} onMutation={mutation} /> : data && !editing && <p className="text-xs text-muted">Eine Sache ausprobieren, später kurz zurückblicken. Freiwillig und ohne neuen Score.</p>}
    {!!history.length && <details className="mt-4 border-t border-line pt-3"><summary className="cursor-pointer text-xs text-muted">Frühere Maßnahmen ({history.length})</summary><div className="mt-3 space-y-5">{history.map((entry) => <ActionEntry key={entry.id} entry={entry} onChange={replace} onRemove={remove} onMutation={mutation} />)}</div></details>}
    {displayedError && <div className="mt-2 flex flex-wrap items-center gap-2"><p role="alert" className="text-xs text-bad">{displayedError}</p>{!data && <button type="button" onClick={() => setRevision((value) => value + 1)} className={button}>Erneut laden</button>}</div>}
  </Card>;
}
