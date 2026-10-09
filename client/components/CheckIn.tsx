"use client";

import { useEffect, useRef, useState } from "react";

type Entry = {
  day: string; energy: number | null; training_effort: number | null; note: string | null;
  session_kind: "run" | "strength" | null; session_external_id: string | null; sick: boolean | null;
};
type Choice = { energy: number | null; sick: boolean };
type CheckIns = { today: string; entries: Entry[] };
const BASE = process.env.NEXT_PUBLIC_API_URL || "/api";
const CHOICES = [
  { value: 1, label: "Wenig Energie", bars: 1 },
  { value: 3, label: "Okay", bars: 2 },
  { value: 5, label: "Viel Energie", bars: 3 },
];

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`${BASE}/checkins${path}`, {
    method, cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error("Check-in konnte nicht gespeichert oder geladen werden.");
  return response.json() as Promise<T>;
}

export const CHECKINS_CHANGED = "milon:checkins-changed";

function Thermometer() {
  return <svg viewBox="0 0 20 20" width="18" height="18" fill="none" aria-hidden="true">
    <path d="M8 3.5a2 2 0 0 1 4 0v8.1a3.5 3.5 0 1 1-4 0z" stroke="currentColor" strokeWidth="1.5" />
    <circle cx="10" cy="14.5" r="1.6" fill="currentColor" /><path d="M10 13V7.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>;
}

function Battery({ bars }: { bars: number }) {
  return <svg viewBox="0 0 30 20" width="26" height="18" fill="none" aria-hidden="true">
    <rect x="1" y="3" width="25" height="14" rx="3" stroke="currentColor" strokeWidth="1.5" />
    <path d="M28 7v6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    {[0, 1, 2].map((index) => <rect key={index} x={5 + index * 6} y="6" width="4" height="8" rx="1" fill="currentColor" opacity={index < bars ? 1 : 0.12} />)}
  </svg>;
}

export function CheckIn() {
  const [data, setData] = useState<CheckIns | null>(null);
  const [confirmedDay, setConfirmedDay] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const saving = useRef(false);
  const revision = useRef(0);
  useEffect(() => {
    let active = true;
    async function refresh() {
      if (saving.current) return;
      const current = ++revision.current;
      try {
        const result = await request<CheckIns>("?days=2");
        if (active && current === revision.current) {
          setData(result);
          setError((previous) => result.entries.some((item) => item.day === result.today) ? previous : null);
        }
      } catch (err) {
        if (active && current === revision.current) setError(err instanceof Error ? err.message : String(err));
      }
    }
    function onVisible() { if (document.visibilityState === "visible") void refresh(); }
    void refresh();
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    const timer = window.setInterval(onVisible, 60_000);
    return () => { active = false; ++revision.current; window.clearInterval(timer);
      window.removeEventListener("focus", onVisible); document.removeEventListener("visibilitychange", onVisible); };
  }, []);
  useEffect(() => {
    if (!confirmedDay || busy || error) return;
    const timer = window.setTimeout(() => setConfirmedDay(null), 2500);
    return () => window.clearTimeout(timer);
  }, [confirmedDay, busy, error]);
  const entry = data?.entries.find((item) => item.day === data.today);
  const sickYesterday = data?.entries.some((item) => item.day !== data.today && item.sick) ?? false;

  async function choose({ energy, sick }: Choice) {
    if (!data || saving.current) return;
    saving.current = true;
    const current = ++revision.current;
    setBusy(true); setError(null);
    try {
      // Read today's current fields immediately before changing only energy.
      const fresh = await request<CheckIns>("?days=2");
      if (current !== revision.current) return;
      setData(fresh);
      const todayEntry = fresh.entries.find((item) => item.day === fresh.today);
      const body = { energy, sick: sick || null, training_effort: todayEntry?.training_effort ?? null, note: todayEntry?.note ?? null,
        session_kind: todayEntry?.session_kind ?? null, session_external_id: todayEntry?.session_external_id ?? null };
      const others = fresh.entries.filter((item) => item.day !== fresh.today);
      if (energy === null && !sick && body.training_effort === null && !body.note && !body.session_external_id) {
        await request(`/${fresh.today}`, "DELETE");
        if (current === revision.current) { setData({ ...fresh, entries: others }); setConfirmedDay(null); }
      } else {
        const updated = await request<Entry>(`/${fresh.today}`, "PUT", body);
        if (current === revision.current) { setData({ ...fresh, entries: [updated, ...others] }); setConfirmedDay(energy === null && !sick ? null : updated.day); }
      }
      window.dispatchEvent(new Event(CHECKINS_CHANGED));
    } catch (err) { if (current === revision.current) setError(err instanceof Error ? err.message : String(err)); }
    finally { saving.current = false; if (current === revision.current) setBusy(false); }
  }

  if (!data && !error) return null;
  if (entry) {
    if (confirmedDay !== data?.today && !busy && !error) return null;
    if (confirmedDay === data?.today || error) return <section aria-label="Check-in gespeichert" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-card border border-accent/15 bg-accent/5 px-4 py-3 text-sm text-accent">
      <span role="status">{busy ? "Wird gespeichert …" : entry.sick ? "Als krank eingetragen ✓ · Gute Besserung" : "Für heute gespeichert ✓"}</span>
      <div className="flex gap-3">
        <button type="button" disabled={busy} onClick={() => void choose({ energy: null, sick: false })} className="text-xs underline underline-offset-4">Zurücknehmen</button>
        {error && <button type="button" onClick={() => { setError(null); setConfirmedDay(null); }} className="text-xs underline underline-offset-4">Schließen</button>}
      </div>
      {error && <p role="alert" className="w-full text-xs text-bad">{error}</p>}
    </section>;
  }

  return <section aria-label="Freiwilliger Energie-Check-in" className="mt-4 rounded-card border border-accent/15 bg-accent/5 p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h2 className="font-display text-lg font-semibold">{sickYesterday ? "Gestern krank – wie geht’s heute?" : "Wie ist dein Akku heute?"}</h2>
        <p className="mt-1 text-xs text-muted">Ein Klick reicht. Nur, wenn du magst.</p>
      </div>
      <div className="grid w-full grid-cols-2 gap-2 sm:w-auto sm:grid-cols-4" role="group" aria-label="Energie heute">
        {CHOICES.map((choice) => <button key={choice.value} type="button" disabled={!data || busy}
          aria-pressed={entry?.energy === choice.value} onClick={() => void choose({ energy: choice.value, sick: false })}
          className={`flex min-h-14 items-center justify-center gap-2 rounded-card border px-2 py-3 text-xs font-semibold transition-colors sm:px-4 ${entry?.energy === choice.value ? "border-accent bg-accent text-white" : "border-accent/15 bg-surface text-accent hover:border-accent hover:bg-accent/5"} disabled:opacity-50`}>
          <Battery bars={choice.bars} /><span>{choice.label}</span>
        </button>)}
        <button type="button" disabled={!data || busy} aria-pressed={entry?.sick === true} onClick={() => void choose({ energy: null, sick: true })}
          className="flex min-h-14 items-center justify-center gap-2 rounded-card border border-sick/60 bg-surface px-2 py-3 text-xs font-semibold text-[#5b3f8c] transition-colors hover:border-sick hover:bg-sick/15 disabled:opacity-50 sm:px-4">
          <Thermometer /><span>{sickYesterday ? "Noch krank" : "Krank"}</span>
        </button>
      </div>
    </div>
    {(entry?.energy != null || busy) && <div className="mt-3 flex items-center gap-3 text-xs text-muted">
      <span role="status">{busy ? "Wird gespeichert …" : "Für heute gespeichert ✓"}</span>
      {entry?.energy != null && <button type="button" disabled={busy} onClick={() => void choose({ energy: null, sick: false })} className="underline underline-offset-4">Zurücknehmen</button>}
    </div>}
    {error && <p role="alert" className="mt-3 text-xs text-bad">{error}</p>}
  </section>;
}
