"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type WalkpadControlState } from "@/lib/api";
import { Card, PageTitle } from "@/components/ui";
import { de } from "@/lib/format";

const STATUS: Record<string, string> = { running: "läuft", paused: "pausiert", stopped: "gestoppt" };
const BTN = "rounded-lg border border-line px-3 py-3 text-base font-semibold disabled:opacity-40";

export default function Laufband() {
  const [st, setSt] = useState<WalkpadControlState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmStart, setConfirmStart] = useState(false);
  const [kmh, setKmh] = useState("3.5");

  useEffect(() => {
    let active = true;
    const poll = () => api.walkpadControl().then((s) => { if (active) setSt(s); }).catch(() => { if (active) setSt(null); });
    poll();
    const t = setInterval(poll, 1000);
    return () => { active = false; clearInterval(t); };
  }, []);

  const send = (body: Parameters<typeof api.walkpadCommand>[0]) => {
    setError(null);
    api.walkpadCommand(body).then((r) => setSt(r.state)).catch((e) => setError(String(e.message ?? e)));
  };
  const ready = !!st?.connected;
  const status = st?.status ? STATUS[st.status] ?? st.status : "unbekannt";
  const result = st?.last_result;
  const wished = parseFloat(kmh.replace(",", "."));
  const startKmh = Math.min(Math.max(Number.isNaN(wished) ? 1 : wished, st?.min_kmh ?? 1), st?.max_kmh ?? 6);

  return <div className="pb-32">
    <PageTitle title="Laufband" sub="Fernbedienung über den Recorder am PC · Steigung nur von Hand" />
    <Card>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-display text-5xl font-extrabold">{de(st?.speed_kmh ?? null, 1)} <span className="text-base font-normal text-muted">km/h</span></p>
        <p className="text-sm">Pad: <b>{ready ? status : "nicht verbunden"}</b>{st?.target_kmh != null && ready ? <span className="text-muted"> · Ziel {de(st.target_kmh, 1)} km/h</span> : null}</p>
      </div>
      <p className="mt-1 text-xs text-muted">
        {st === null ? "Server nicht erreichbar." : !st.recorder_online ? "Recorder auf dem PC läuft nicht." : !st.connected ? "Recorder läuft, Pad nicht verbunden (aus, oder die Sportstech-App ist verbunden)." : `Verbunden mit ${st.device ?? "Pad"} · Höchsttempo ${de(st.max_kmh, 1)} km/h`}
      </p>

      <div className="mt-4 grid grid-cols-4 gap-2">
        {([["slower", 0.5, "−0,5"], ["slower", 0.1, "−0,1"], ["faster", 0.1, "+0,1"], ["faster", 0.5, "+0,5"]] as const).map(([action, step, label]) =>
          <button key={label} type="button" disabled={!ready} className={BTN} onClick={() => send({ action, step })}>{label}</button>)}
      </div>
      <div className="mt-3 flex gap-2">
        <input type="number" inputMode="decimal" min={1} max={st?.max_kmh ?? 6} step={0.1} value={kmh} onChange={(e) => setKmh(e.target.value)}
          className="w-28 rounded border border-line bg-surface px-2 py-2 text-base" aria-label="Tempo in km/h" />
        <button type="button" disabled={!ready} className={BTN} onClick={() => { const v = parseFloat(kmh.replace(",", ".")); if (!Number.isNaN(v)) send({ action: "speed", kmh: v }); }}>Tempo setzen</button>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        {confirmStart
          ? <button type="button" disabled={!ready} className={`${BTN} border-accent bg-accent text-white`} onClick={() => { setConfirmStart(false); send({ action: "start", confirm: true, kmh: startKmh }); }}>Band startet – wirklich?</button>
          : <button type="button" disabled={!ready} className={BTN} onClick={() => setConfirmStart(true)}>Start mit {de(startKmh, 1)} km/h</button>}
        <button type="button" disabled={!ready} className={BTN} onClick={() => { setConfirmStart(false); send({ action: "pause" }); }}>Pause</button>
      </div>
      {confirmStart && <button type="button" className="mt-2 text-xs text-muted underline underline-offset-4" onClick={() => setConfirmStart(false)}>Abbrechen</button>}
      <p className="mt-2 text-[11px] text-muted">Das Pad startet nach ~3 s Countdown mit 1,0 km/h; das Wunschtempo (Feld oben) setzt der Recorder, sobald das Band läuft.</p>

      {error && <p className="mt-3 text-sm text-bad">{error}</p>}
      {result && <p className={`mt-3 text-xs ${result.ok ? "text-muted" : "text-bad"}`}>Letzter Befehl: {result.ok ? "ausgeführt" : result.message}</p>}
    </Card>
    <p className="mt-4 text-xs text-muted">
      Befehle älter als 3 s verwirft der Recorder. Bricht die Verbindung ab, läuft das Band im zuletzt gesetzten Tempo weiter – es wird nie automatisch schneller.
      Sessions und Schritte stehen auf <Link href="/gesundheit" className="underline underline-offset-4">Gesundheit</Link>.
    </p>

    <div className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-bg/95 p-3 backdrop-blur md:left-60">
      <button type="button" onClick={() => { setConfirmStart(false); send({ action: "stop" }); }}
        className="w-full rounded-xl bg-bad py-5 text-2xl font-extrabold tracking-wide text-white shadow-lg active:scale-[0.99]">
        STOPP
      </button>
    </div>
  </div>;
}
