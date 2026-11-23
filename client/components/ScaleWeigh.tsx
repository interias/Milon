"use client";

// Wiegen direkt über Web Bluetooth (Arboleaf CS20L / QN-Protokoll, lib/scale/qnScale.ts).
// measureOnce() muss direkt aus dem Klick heraus starten (Chrome verlangt eine Nutzergeste
// für requestDevice) — deshalb kein await davor.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ScaleMeasurement } from "@/lib/api";
import { measureOnce, type ScaleReading } from "@/lib/scale/qnScale";
import { de, dm } from "@/lib/format";

type Phase = "idle" | "measuring" | "saving" | "saved" | "error";
export const WEIGHT_SAVED = "milon:weight-saved";

const time = (iso: string) => new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });

function friendly(e: unknown): string {
  const err = e as { name?: string; message?: string };
  if (err?.name === "NotFoundError") return "Keine Waage gewählt. Waage antippen, damit sie aufwacht, und nochmal versuchen – oder „Alle Geräte anzeigen“.";
  if (err?.name === "SecurityError") return "Bluetooth ist hier nicht erlaubt. Seite über HTTPS öffnen und Chrome die Bluetooth-Berechtigung geben.";
  if (err?.name === "NetworkError") return "Verbindung zur Waage fehlgeschlagen. Ist die Arboleaf-App noch offen? Sie hält die Verbindung fest.";
  return err?.message || String(e);
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

export function ScaleWeigh({ onSaved, compact = false }: { onSaved?: () => void; compact?: boolean }) {
  const [support, setSupport] = useState<"unknown" | "ok" | "insecure" | "missing">("unknown");
  const [phase, setPhase] = useState<Phase>("idle");
  const [live, setLive] = useState<number | null>(null);
  const [reading, setReading] = useState<ScaleReading | null>(null);
  const [duplicate, setDuplicate] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);
  const [recent, setRecent] = useState<ScaleMeasurement[] | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [ready, setReady] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [logOpen, setLogOpen] = useState(false);
  const logRef = useRef<string[]>([]);

  useEffect(() => {
    if (phase !== "measuring") return;
    const started = Date.now();
    const id = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, [phase]);

  useEffect(() => {
    // erst im Browser prüfen, sonst weicht das Server-HTML ab
    if (!window.isSecureContext) setSupport("insecure");
    else setSupport("bluetooth" in navigator ? "ok" : "missing");
  }, []);

  const loadRecent = useCallback(() => {
    api.scaleList(60).then((r) => setRecent(r.measurements.slice(0, 5))).catch(() => setRecent(null));
  }, []);
  useEffect(loadRecent, [loadRecent]);

  const addLog = (line: string) => {
    if (line.includes("Bereit – jetzt barfuß")) setReady(true);
    logRef.current = [...logRef.current, line].slice(-400);
    setLog(logRef.current);
  };

  const save = async (r: ScaleReading) => {
    setPhase("saving");
    setError(null);
    try {
      const res = await api.scaleSave(r);
      setDuplicate(res.duplicate);
      addLog(res.duplicate ? "Backend: schon gespeichert (Dublette)" : `Backend: gespeichert (#${res.measurement.id})`);
      setPhase("saved");
      loadRecent();
      onSaved?.();
      window.dispatchEvent(new Event(WEIGHT_SAVED));
    } catch (e) {
      addLog(`! Speichern fehlgeschlagen: ${friendly(e)}`);
      setError(`Messung nicht gespeichert: ${friendly(e)}`);
      setPhase("error");
    }
  };

  const start = (acceptAllDevices = false) => {
    logRef.current = [];
    setLog([]);
    setLive(null);
    setReading(null);
    setDuplicate(false);
    setError(null);
    setCopied(false);
    setReady(false);
    setElapsed(0);
    setPhase("measuring");
    measureOnce({ acceptAllDevices, onLiveWeight: setLive, onLog: addLog })
      .then((r) => { setReading(r); setLive(r.weightKg); return save(r); })
      .catch((e) => { addLog(`! ${friendly(e)}`); setError(friendly(e)); setPhase("error"); });
  };

  const busy = phase === "measuring" || phase === "saving";

  if (support === "insecure" || support === "missing") {
    return <div className="rounded-lg border border-line bg-surface-alt p-4 text-sm">
      <p className="font-semibold">Wiegen geht in diesem Browser nicht</p>
      <p className="mt-1 text-muted">{support === "insecure"
        ? "Web Bluetooth braucht eine sichere Verbindung. Milon über HTTPS (Tailscale) öffnen, nicht über http://<IP>."
        : "Bitte in Chrome öffnen. Samsung Internet, Firefox und iOS-Browser können kein Web Bluetooth."}</p>
    </div>;
  }

  const waiting = phase === "measuring" && live == null;
  const status = phase === "measuring"
    ? (!ready ? "Verbinde mit der Waage …"
      : live == null ? (elapsed >= 20 ? "Noch kein Gewicht empfangen. Stehst du schon drauf? Sonst: Log kopieren." : "Bereit – jetzt barfuß draufstellen")
      : "Messe – stillstehen …")
    : phase === "saving" ? "Stabil. Speichere …" : null;

  return <div className="min-w-0">
    <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
      <button type="button" disabled={busy || support !== "ok"} onClick={() => start(false)}
        className="min-h-14 rounded-lg bg-accent px-8 text-lg font-semibold text-white disabled:opacity-50">
        {phase === "measuring" ? "Läuft …" : phase === "saving" ? "Speichere …" : "Wiegen"}
      </button>
      <div className="flex items-baseline gap-2" aria-live="polite">
        <span className={`font-display text-5xl font-extrabold tabular-nums ${phase === "saved" ? "text-accent" : live == null ? "text-muted/40" : ""}`}>
          {live == null ? "–,–" : de(live, phase === "saved" ? 2 : 1)}
        </span>
        <span className="text-base text-muted">kg</span>
        {phase === "saved" && <span className="text-3xl text-accent" aria-label="gespeichert">✓</span>}
      </div>
    </div>
    <p className={`mt-2 min-h-5 text-sm ${waiting && ready && elapsed < 20 ? "font-semibold text-accent" : ""}`} role="status">
      {status}
      {phase === "saved" && reading && (duplicate
        ? "Diese Messung war schon gespeichert."
        : `Gespeichert · ${reading.source === "stored" ? "aus dem Waagenspeicher" : "live"} · Widerstand ${reading.r1}/${reading.r2}`)}
      {phase === "error" && <span className="text-bad">{error}</span>}
    </p>
    <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
      <button type="button" disabled={busy || support !== "ok"} onClick={() => start(true)}
        className="py-1.5 text-muted underline underline-offset-4 disabled:opacity-50">Alle Geräte anzeigen</button>
      <button type="button" onClick={() => setLogOpen((open) => !open)} className="py-1.5 text-muted underline underline-offset-4">
        {logOpen ? "Log ausblenden" : `Log (${log.length})`}</button>
      <button type="button" disabled={!log.length} onClick={() => copyText(log.join("\n")).then(setCopied)}
        className="py-1.5 text-accent underline underline-offset-4 disabled:opacity-40">{copied ? "Kopiert ✓" : "Log kopieren"}</button>
      {phase === "error" && reading && <button type="button" onClick={() => save(reading)}
        className="rounded-lg border border-line px-3 py-1.5">Erneut speichern</button>}
    </div>
    {logOpen && <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded bg-surface-alt p-2 font-mono text-[11px] leading-snug">
      {log.length ? log.join("\n") :"Noch nichts – nach „Wiegen“ erscheinen hier alle Bluetooth-Pakete."}
    </pre>}

    {!compact && <details className="mt-3 text-xs text-muted">
      <summary className="cursor-pointer py-1">Anleitung</summary>
      <ol className="mt-1 list-decimal space-y-1 pl-5">
        <li>Arboleaf-App schließen – sie hält sonst die Verbindung zur Waage.</li>
        <li>Waage antippen, damit sie aufwacht.</li>
        <li>„Wiegen“ tippen und im Chrome-Dialog die Waage wählen (meist „QN-Scale“).</li>
        <li>Erst wenn „Bereit“ erscheint, barfuß draufstellen und stillstehen, bis das Häkchen kommt.</li>
      </ol>
    </details>}

    {!compact && recent && recent.length > 0 && <details className="mt-1 text-sm">
      <summary className="cursor-pointer py-1 text-xs text-muted">Letzte Wiegungen per Bluetooth ({recent.length})</summary>
      <ul className="mt-1 divide-y divide-line">
        {recent.map((m) => <li key={m.id} className="flex items-center justify-between gap-3 py-1.5">
          <span className="min-w-0 truncate">{dm(m.measured_at)} {time(m.measured_at)} · <b>{de(m.weight_kg, 2)} kg</b>
            <span className="text-xs text-muted"> · r {m.r1 ?? "–"}/{m.r2 ?? "–"}</span></span>
          {confirmDelete === m.id
            ? <span className="flex shrink-0 gap-2 text-xs">
                <button type="button" className="text-bad underline" onClick={() => api.scaleDelete(m.id).then(() => { setConfirmDelete(null); loadRecent(); onSaved?.(); window.dispatchEvent(new Event(WEIGHT_SAVED)); })}>Sicher löschen</button>
                <button type="button" className="text-muted underline" onClick={() => setConfirmDelete(null)}>Nein</button>
              </span>
            : <button type="button" className="shrink-0 text-xs text-muted underline" onClick={() => setConfirmDelete(m.id)}>Löschen</button>}
        </li>)}
      </ul>
    </details>}
  </div>;
}
