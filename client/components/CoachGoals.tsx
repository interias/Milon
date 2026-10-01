"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api, type CoachGoal, type CoachProfile } from "@/lib/api";
import { Card, CardTitle, Loading } from "@/components/ui";

const INPUT = "w-full min-w-0 rounded-lg border border-line bg-surface-alt px-3 py-2 text-base text-ink placeholder:text-muted focus:border-accent focus:outline-none sm:text-sm";
const STATUS = { active: "Aktiv", past: "Termin vergangen", achieved: "Erreicht", archived: "Archiviert" };

function newId() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export default function CoachGoals() {
  const [profile, setProfile] = useState<CoachProfile | null>(null);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState(false);

  function load() {
    setLoadError(null);
    api.coachProfileGet().then((data) => {
      setProfile(data);
      setSavedIds(new Set(data.goals.map((goal) => goal.id)));
    }).catch((error) => setLoadError(String(error)));
  }

  useEffect(() => { load(); }, []);

  function update(id: string, change: Partial<CoachGoal>) {
    setMessage(null);
    setProfile((current) => current && ({ ...current, goals: current.goals.map((goal) => goal.id === id ? { ...goal, ...change } : goal) }));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profile) return;
    setMessage(null);
    setSaveError(false);
    const invalid = profile.goals.find((goal) => !goal.name.trim() || (goal.end_date && (!goal.start_date || goal.end_date < goal.start_date)));
    if (invalid) {
      setSaveError(true);
      setMessage("Bitte gib jedem Ziel einen Namen und wähle ein Enddatum ab dem Startdatum.");
      return;
    }
    setBusy(true);
    try {
      const updated = await api.coachProfileUpdate({
        context: profile.context,
        goals: profile.goals.map(({ effective_status, ...goal }) => ({ ...goal, name: goal.name.trim() })),
      });
      setProfile(updated);
      setSavedIds(new Set(updated.goals.map((goal) => goal.id)));
      setMessage("Ziele & Rahmenbedingungen gespeichert. Sie gelten für neue Coach-Antworten.");
    } catch (error) {
      setSaveError(true);
      setMessage(`Speichern fehlgeschlagen: ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-4">
      <CardTitle title="Coach · Ziele & Rahmenbedingungen" sub="Wettkämpfe, persönliche Ziele und verfügbare Trainingszeit" />
      {loadError ? (
        <div role="alert" className="text-sm text-bad">
          <p>Ziele konnten nicht geladen werden: {loadError}</p>
          <button type="button" onClick={load} className="mt-2 underline">Erneut laden</button>
        </div>
      ) : !profile ? <Loading /> : (
        <form onSubmit={save}>
          <fieldset disabled={busy} className="min-w-0 space-y-4 disabled:opacity-60">
            <p className="text-sm text-muted">Nach dem Termin bleibt ein Ziel erhalten und wird als „Termin vergangen“ behandelt. „Erreicht“ setzt du selbst. Ziele ohne Datum bleiben aktiv.</p>
            {profile.goals.length === 0 && <p className="text-sm text-muted">Noch keine Ziele eingetragen.</p>}
            {profile.goals.map((goal, index) => (
              <fieldset key={goal.id} className="min-w-0 rounded-lg border border-line p-3 sm:p-4">
                <legend className="px-1 text-sm font-semibold">Ziel {index + 1}{savedIds.has(goal.id) && <span className="ml-2 font-normal text-muted">· {STATUS[goal.status === "active" ? (goal.effective_status === "past" ? "past" : "active") : goal.status]}</span>}</legend>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="block sm:col-span-2">
                    <span className="mb-1 block text-xs text-muted">Name *</span>
                    <input required maxLength={200} value={goal.name} onChange={(event) => update(goal.id, { name: event.target.value })} className={INPUT} placeholder="z. B. Halbmarathon Düsseldorf" />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs text-muted">Datum / Beginn (optional)</span>
                    <input type="date" value={goal.start_date ?? ""} onChange={(event) => update(goal.id, { start_date: event.target.value || null })} className={INPUT} />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs text-muted">Ende bei Zeitraum (optional)</span>
                    <input type="date" min={goal.start_date ?? undefined} value={goal.end_date ?? ""} onChange={(event) => update(goal.id, { end_date: event.target.value || null })} className={INPUT} />
                  </label>
                  <label className="block sm:col-span-2">
                    <span className="mb-1 block text-xs text-muted">Gewünschtes Ergebnis (optional)</span>
                    <textarea rows={2} maxLength={2000} value={goal.target} onChange={(event) => update(goal.id, { target: event.target.value })} className={INPUT} placeholder="z. B. gesund ankommen oder eine gewünschte Zielzeit" />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs text-muted">Priorität</span>
                    <select value={goal.priority} onChange={(event) => update(goal.id, { priority: event.target.value as CoachGoal["priority"] })} className={INPUT}>
                      <option value="high">Hoch</option><option value="normal">Normal</option><option value="low">Niedrig</option>
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs text-muted">Status</span>
                    <select value={goal.status} onChange={(event) => update(goal.id, { status: event.target.value as CoachGoal["status"] })} className={INPUT}>
                      <option value="active">Aktiv</option><option value="achieved">Erreicht</option><option value="archived">Archiviert</option>
                    </select>
                  </label>
                </div>
                {!savedIds.has(goal.id) && <button type="button" onClick={() => { setMessage(null); setProfile({ ...profile, goals: profile.goals.filter((entry) => entry.id !== goal.id) }); }} className="mt-3 text-sm text-bad underline">Entwurf entfernen</button>}
              </fieldset>
            ))}
            <button type="button" disabled={profile.goals.length >= 50} onClick={() => {
              setMessage(null);
              setProfile({ ...profile, goals: [...profile.goals, { id: newId(), name: "", start_date: null, end_date: null, target: "", priority: "normal", status: "active", effective_status: "active" }] });
            }} className="rounded-lg border border-line px-3 py-2 text-sm font-semibold text-accent disabled:opacity-50">+ Ziel hinzufügen</button>
            <label className="block">
              <span className="mb-1 block text-sm font-semibold">Rahmenbedingungen (optional)</span>
              <textarea rows={4} maxLength={8000} value={profile.context} onChange={(event) => { setMessage(null); setProfile({ ...profile, context: event.target.value }); }} className={INPUT} placeholder="z. B. drei Trainingstage pro Woche, Krafttraining beibehalten, verfügbare Ausrüstung" />
            </label>
            <p className="text-xs text-muted">Gespeicherte Ziele kannst du über den Status archivieren. Vergangene und archivierte Ziele bleiben zur Einordnung erhalten.</p>
            <button type="submit" className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white hover:brightness-110 sm:w-auto">{busy ? "speichert …" : "Ziele & Rahmenbedingungen speichern"}</button>
          </fieldset>
          {message && <p role={saveError ? "alert" : "status"} className={`mt-3 text-sm ${saveError ? "text-bad" : "text-good"}`}>{message}</p>}
        </form>
      )}
    </Card>
  );
}
