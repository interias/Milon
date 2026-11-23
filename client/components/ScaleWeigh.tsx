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
  const logRef = useRef<string[]>([]);

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

  return <div className="min-w-0">
    {!compact && <ol className="mb-4 list-decimal space-y-1 pl-5 text-sm text-muted">
      <li>Arboleaf-App schließen – sie hält sonst die Verbindung zur Waage.</li>
      <li>Waage antippen, damit sie aufwacht.</li>
      <li>„Wiegen“ tippen und im Chrome-Dialog die Waage wählen (meist „QN-Scale“).</li>
      <li>Barfuß draufstellen und stillstehen, bis das Häkchen erscheint.</li>
    </ol>}

    <div className="flex flex-wrap items-center gap-3">
      <button type="button" disabled={busy || support !== "ok"} onClick={() => start(false)}
        className="min-h-14 rounded-lg bg-accent px-8 text-lg font-semibold text-white disabled:opacity-50">
        {phase === "measuring" ? "Verbinde / messe …" : phase === "saving" ? "Speichere …" : "Wiegen"}
      </button>
      <button type="button" disabled={busy || support !== "ok"} onClick={() => start(true)}
        className="py-2 text-xs text-muted underline underline-offset-4 disabled:opacity-50">Alle Geräte anzeigen</button>
    </div>

    <div className="mt-5 flex items-baseline gap-3" aria-live="polite">
      <span className={`font-display text-6xl font-extrabold tabular-nums ${phase === "saved" ? "text-accent" : live == null ? "text-muted/40" : ""}`}>
        {live == null ? "–,–" : de(live, phase === "saved" ? 2 : 1)}
      </span>
      <span className="text-lg text-muted">kg</span>
      {phase === "saved" && <span className="text-3xl text-accent" aria-label="gespeichert">✓</span>}
    </div>
    <p className="mt-1 min-h-5 text-sm" role="status">
      {phase === "measuring" && (live == null ? "Warte auf die Waage …" : "Messe – stillstehen …")}
      {phase === "saving" && "Stabil. Speichere …"}
      {phase === "saved" && reading && (duplicate
        ? "Diese Messung war schon gespeichert."
        : `Gespeichert · ${reading.source === "stored" ? "aus dem Waagenspeicher" : "live"} · Widerstand ${reading.r1}/${reading.r2}`)}
      {phase === "error" && <span className="text-bad">{error}</span>}
    </p>
    {phase === "error" && reading && <button type="button" onClick={() => save(reading)}
      className="mt-2 rounded-lg border border-line px-4 py-2 text-sm">Erneut speichern</button>}

    {recent && recent.length > 0 && <div className="mt-4">
      <p className="text-xs font-semibold text-muted">Letzte Wiegungen per Bluetooth</p>
      <ul className="mt-1 divide-y divide-line text-sm">
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
    </div>}

    <details className="mt-4 text-xs">
      <summary className="cursor-pointer py-1 text-muted">Debug-Log ({log.length} Zeilen)</summary>
      <div className="mt-2 flex gap-3">
        <button type="button" disabled={!log.length} className="rounded border border-line px-3 py-1.5 disabled:opacity-50"
          onClick={() => copyText(log.join("\n")).then(setCopied)}>{copied ? "Kopiert ✓" : "Log kopieren"}</button>
      </div>
      <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded bg-surface-alt p-2 font-mono text-[11px] leading-snug">
        {log.length ? log.join("\n") : "Noch nichts – nach „Wiegen“ erscheinen hier alle Bluetooth-Pakete."}
      </pre>
    </details>
  </div>;
}
